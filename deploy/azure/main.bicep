@description('Deployment prefix')
param name string = 'mercury'

@description('Globally unique, lowercase Azure Container Registry name')
param registryName string

@description('Azure region')
param location string = resourceGroup().location

@description('Immutable ACR image reference including its sha256 digest')
param image string

@secure()
@description('Scoped, read-only Doppler production service token')
param dopplerToken string

@secure()
@description('PostgreSQL administrator password used only for initial provisioning')
param postgresPassword string

param postgresAdmin string = 'mercuryadmin'

resource network 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${name}-vnet'
  location: location
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
  name: 'private.postgres.database.azure.com'
  location: 'global'
}

resource privateDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDns
  name: '${name}-postgres-link'
  location: 'global'
  properties: {
    virtualNetwork: {
      id: network.id
    }
    registrationEnabled: false
  }
}

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: '${name}-postgres'
  location: location
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

resource postgresExtensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: postgres
  name: 'azure.extensions'
  properties: {
    source: 'user-override'
    value: 'VECTOR'
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: registryName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
    policies: {
      retentionPolicy: {
        days: 7
        status: 'enabled'
      }
    }
  }
}

resource pullIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${name}-pull'
  location: location
}

var acrPullRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions'
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

resource containerEnvironment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: '${name}-environment'
  location: location
  properties: {
    vnetConfiguration: {
      infrastructureSubnetId: appsSubnet.id
      internal: false
    }
  }
}

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
]

var registryConfiguration = [
  {
    server: registry.properties.loginServer
    identity: pullIdentity.id
  }
]

resource web 'Microsoft.App/containerApps@2025-01-01' = {
  name: '${name}-web'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${pullIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
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
  name: '${name}-worker'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${pullIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerEnvironment.id
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
          command: [
            'python'
          ]
          args: [
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
  name: '${name}-migrate'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${pullIdentity.id}': {}
    }
  }
  properties: {
    environmentId: containerEnvironment.id
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
            'flask --app wsgi:app db upgrade && procrastinate --app=mercury.jobs.cli.app schema --apply'
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
