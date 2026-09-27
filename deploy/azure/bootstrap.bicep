@description('Globally unique, lowercase Azure Container Registry name')
param registryName string

param location string = resourceGroup().location

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: registryName
  location: location
  // Must match main.bicep's shared registry tags so the two deployments do not flap.
  tags: {
    app: 'mercury'
  }
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

output loginServer string = registry.properties.loginServer
