@description('Deployment prefix')
param name string = 'mercury'
@description('Azure region')
param location string = resourceGroup().location
@description('Immutable ACR image reference including digest')
param image string
@secure()
@description('Scoped read-only Doppler service token')
param dopplerToken string
@secure()
@description('PostgreSQL administrator password used only for initial provisioning')
param postgresPassword string
param postgresAdmin string = 'mercuryadmin'
param postgresVersion string = '17'

resource network 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${name}-vnet'
  location: location
  properties: {
    addressSpace: { addressPrefixes: ['10.42.0.0/16'] }
    subnets: [
      { name: 'apps'; properties: { addressPrefix: '10.42.0.0/23' } }
      { name: 'database'; properties: { addressPrefix: '10.42.2.0/24'; delegations: [{ name: 'postgres'; properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' } }] } }
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
  properties: { virtualNetwork: { id: network.id }; registrationEnabled: false }
}

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: '${name}-postgres'
  location: location
  sku: { name: 'Standard_B1ms'; tier: 'Burstable' }
  properties: {
    administratorLogin: postgresAdmin
    administratorLoginPassword: postgresPassword
    version: postgresVersion
    storage: { storageSizeGB: 32 }
    backup: { backupRetentionDays: 7; geoRedundantBackup: 'Disabled' }
    network: {
      delegatedSubnetResourceId: network.properties.subnets[1].id
      privateDnsZoneArmResourceId: privateDns.id
      publicNetworkAccess: 'Disabled'
    }
    highAvailability: { mode: 'Disabled' }
  }
  dependsOn: [privateDnsLink]
}

resource containerEnvironment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: '${name}-environment'
  location: location
  properties: { vnetConfiguration: { infrastructureSubnetId: network.properties.subnets[0].id } }
}

var commonSecrets = [{ name: 'doppler-token'; value: dopplerToken }]
var commonEnv = [
  { name: 'APP_ENV'; value: 'production' }
  { name: 'DOPPLER_TOKEN'; secretRef: 'doppler-token' }
]

resource web 'Microsoft.App/containerApps@2025-01-01' = {
  name: '${name}-web'
  location: location
  properties: {
    managedEnvironmentId: containerEnvironment.id
    configuration: { ingress: { external: true; targetPort: 8000; transport: 'http'; allowInsecure: false }; secrets: commonSecrets }
    template: {
      containers: [{ name: 'web'; image: image; env: commonEnv; resources: { cpu: json('0.25'); memory: '0.5Gi' } }]
      scale: { minReplicas: 0; maxReplicas: 3; rules: [{ name: 'http'; http: { metadata: { concurrentRequests: '50' } } }] }
    }
  }
}

resource worker 'Microsoft.App/containerApps@2025-01-01' = {
  name: '${name}-worker'
  location: location
  properties: {
    managedEnvironmentId: containerEnvironment.id
    configuration: { activeRevisionsMode: 'Single'; secrets: commonSecrets }
    template: {
      containers: [{ name: 'worker'; image: image; command: ['python']; args: ['-m', 'mercury.jobs.worker']; env: commonEnv; resources: { cpu: json('0.5'); memory: '1Gi' } }]
      scale: { minReplicas: 1; maxReplicas: 1 }
    }
  }
}

output postgresHost string = postgres.properties.fullyQualifiedDomainName
output webHostname string = web.properties.configuration.ingress.fqdn

