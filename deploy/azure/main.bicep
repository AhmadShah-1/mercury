@description('Resource base name; resources are named <name>-<role>-<environmentName>')
param name string = 'mercury'

@description('Deployment name. Both environments run APP_ENV=production; this only separates resources.')
@allowed([
  'staging'
  'production'
])
param environmentName string

@description('Globally unique, lowercase Azure Container Registry name, shared by both environments')
param registryName string

@description('Azure region')
param location string = resourceGroup().location

@description('Immutable ACR image reference including its sha256 digest')
param image string

@description('Git commit deployed, exposed to the application as RELEASE_ID')
param releaseId string

@secure()
@description('Scoped, read-only Doppler service token for this environment\'s config')
param dopplerToken string

@secure()
@description('PostgreSQL administrator password used only for initial provisioning')
param postgresPassword string

param postgresAdmin string = 'mercuryadmin'

@description('Hostname of APP_BASE_URL (for example app.example.com). Probes send it as Host because Mercury rejects untrusted Host headers.')
param appHostname string

@description('Managed certificate already bound to appHostname, or empty before the first binding. Redeploying without it would remove the custom domain.')
param customDomainCertificateId string = ''

var tags = {
  app: name
  environment: environmentName
}

// The registry is shared by both environments, so it carries no environment tag.
var sharedTags = {
  app: name
}

resource network 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${name}-vnet-${environmentName}'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.42.0.0/16'
      ]
    }
  }
}

resource appsSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: network
  name: 'apps'
  properties: {
    addressPrefix: '10.42.0.0/23'
    delegations: [
      {
        name: 'container-apps'
        properties: {
          serviceName: 'Microsoft.App/environments'
        }
      }
    ]
  }
}

resource databaseSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: network
  name: 'database'
  properties: {
    addressPrefix: '10.42.2.0/24'
    delegations: [
      {
        name: 'postgres'
        properties: {
          serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers'
        }
      }
    ]
  }
}

resource privateDns 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: '${name}-${environmentName}.private.postgres.database.azure.com'
  location: 'global'
  tags: tags
}

resource privateDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDns
  name: '${name}-postgres-link-${environmentName}'
  location: 'global'
  tags: tags
  properties: {
    virtualNetwork: {
      id: network.id
    }
    registrationEnabled: false
  }
}

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: '${name}-postgres-${environmentName}'
  location: location
  tags: tags
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    administratorLogin: postgresAdmin
    administratorLoginPassword: postgresPassword
    version: '17'
    storage: {
      storageSizeGB: 32
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    network: {
      delegatedSubnetResourceId: databaseSubnet.id
      privateDnsZoneArmResourceId: privateDns.id
      publicNetworkAccess: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
  }
  dependsOn: [
    privateDnsLink
  ]
}

resource mercuryDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: 'mercury'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

// Allow-list pgvector; the application migration then runs CREATE EXTENSION vector.
resource postgresExtensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: postgres
  name: 'azure.extensions'
  properties: {
    source: 'user-override'
    value: 'VECTOR'
  }
  // Server-level operations are serialized to avoid ServerIsBusy conflicts.
  dependsOn: [
    mercuryDatabase
  ]
}

// Basic tier: no admin user; untagged-manifest retention policies require Premium, so old
// digests are pruned by the documented operations procedure instead.
resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: registryName
  location: location
  tags: sharedTags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource pullIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${name}-pull-${environmentName}'
  location: location
  tags: tags
}

// Built-in AcrPull role.
var acrPullRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '7f951dda-4ed3-4680-a7ca-43fe172d538d'
)

resource registryPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, pullIdentity.id, acrPullRoleDefinitionId)
  scope: registry
  properties: {
    principalId: pullIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPullRoleDefinitionId
  }
}

// Retains sanitized application logs (including deletion audit events) for 30 days. The daily
// cap bounds runaway cost; normal volume stays well inside the monthly free ingestion allowance.
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${name}-logs-${environmentName}'
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    workspaceCapping: {
      dailyQuotaGb: json('0.5')
    }
  }
}

resource containerEnvironment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: '${name}-environment-${environmentName}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
    // A workload-profiles environment is required for a subnet delegated to Microsoft.App.
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    vnetConfiguration: {
      infrastructureSubnetId: appsSubnet.id
      internal: false
    }
  }
}

var probeHeaders = [
  {
    name: 'Host'
    value: appHostname
  }
]

var commonSecrets = [
  {
    name: 'doppler-token'
    value: dopplerToken
  }
]

var commonEnv = [
  {
    name: 'APP_ENV'
    value: 'production'
  }
  {
    name: 'DOPPLER_TOKEN'
    secretRef: 'doppler-token'
  }
  {
    name: 'RELEASE_ID'
    value: releaseId
  }
]

var registryConfiguration = [
  {
    server: registry.properties.loginServer
    identity: pullIdentity.id
  }
]

resource web 'Microsoft.App/containerApps@2025-01-01' = {
  name: '${name}-web-${environmentName}'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${pullIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
        customDomains: empty(customDomainCertificateId)
          ? []
          : [
              {
                name: appHostname
                certificateId: customDomainCertificateId
                bindingType: 'SniEnabled'
              }
            ]
      }
      registries: registryConfiguration
      secrets: commonSecrets
    }
    template: {
      containers: [
        {
          name: 'web'
          image: image
          env: commonEnv
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health/live'
                port: 8000
                scheme: 'HTTP'
                httpHeaders: probeHeaders
              }
              initialDelaySeconds: 10
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health/ready'
                port: 8000
                scheme: 'HTTP'
                httpHeaders: probeHeaders
              }
              initialDelaySeconds: 10
              periodSeconds: 15
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 3
        rules: [
          {
            name: 'http'
            http: {
              metadata: {
                concurrentRequests: '50'
              }
            }
          }
        ]
      }
    }
  }
  dependsOn: [
    registryPull
  ]
}

resource worker 'Microsoft.App/containerApps@2025-01-01' = {
  name: '${name}-worker-${environmentName}'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${pullIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      registries: registryConfiguration
      secrets: commonSecrets
    }
    template: {
      containers: [
        {
          name: 'worker'
          image: image
          // Override only CMD; the image ENTRYPOINT performs fail-closed Doppler injection.
          args: [
            'python'
            '-m'
            'mercury.jobs.worker'
          ]
          env: commonEnv
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
  dependsOn: [
    registryPull
  ]
}

resource migrationJob 'Microsoft.App/jobs@2025-01-01' = {
  name: '${name}-migrate-${environmentName}'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${pullIdentity.id}': {}
    }
  }
  properties: {
    environmentId: containerEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 1800
      replicaRetryLimit: 1
      registries: registryConfiguration
      secrets: commonSecrets
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
    }
    template: {
      containers: [
        {
          name: 'migrate'
          image: image
          command: [
            '/app/deploy/entrypoint.sh'
          ]
          args: [
            '/bin/sh'
            '-c'
            'flask --app wsgi:app db upgrade && flask --app wsgi:app queue-schema'
          ]
          env: commonEnv
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
      ]
    }
  }
  dependsOn: [
    mercuryDatabase
    postgresExtensions
    registryPull
  ]
}

output registryLoginServer string = registry.properties.loginServer
output postgresHost string = postgres.properties.fullyQualifiedDomainName
output webHostname string = web.properties.configuration.ingress.fqdn
output migrationJobName string = migrationJob.name
