$ErrorActionPreference = "Stop"

$azCommand = Get-Command az -ErrorAction SilentlyContinue
if (-not $azCommand) {
    $defaultAzPath = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
    if (-not (Test-Path -LiteralPath $defaultAzPath)) {
        throw "Azure CLI was not found. Install Azure CLI and sign in with az login."
    }
    $az = $defaultAzPath
} else {
    $az = $azCommand.Source
}

$resourceGroup = "rg-dayat-echo-hackathon"
$appName = "dayat-echo-20261105-150954"
$planName = "yume1856_asp_2643"
$startup = "python -m uvicorn app.main:app --app-dir /home/site/wwwroot --host 0.0.0.0 --port 8000"
$zipPath = Join-Path $env:TEMP ("dayat-api-{0}.zip" -f [guid]::NewGuid().ToString("N"))

Push-Location $PSScriptRoot
try {
    & $az group show --name $resourceGroup --output none
    if ($LASTEXITCODE -ne 0) {
        & $az group create --name $resourceGroup --location koreacentral --output none
        if ($LASTEXITCODE -ne 0) {
            throw "Azure resource group creation failed with exit code $LASTEXITCODE."
        }
    }

    & $az webapp show --resource-group $resourceGroup --name $appName --query name --output tsv 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        & $az appservice plan show --resource-group $resourceGroup --name $planName --query name --output tsv 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            & $az appservice plan create `
                --resource-group $resourceGroup `
                --name $planName `
                --location koreacentral `
                --is-linux `
                --sku F1 `
                --output none
            if ($LASTEXITCODE -ne 0) {
                throw "Azure App Service plan creation failed with exit code $LASTEXITCODE."
            }
        }

        & $az webapp create `
            --resource-group $resourceGroup `
            --plan $planName `
            --name $appName `
            --runtime PYTHON:3.12 `
            --https-only true `
            --output none
        if ($LASTEXITCODE -ne 0) {
            throw "Azure web app creation failed with exit code $LASTEXITCODE."
        }
    }

    & $az webapp config set `
        --resource-group $resourceGroup `
        --name $appName `
        --startup-file $startup `
        --output none
    if ($LASTEXITCODE -ne 0) {
        throw "Azure App Service startup configuration failed with exit code $LASTEXITCODE."
    }

    & $az webapp config appsettings set `
        --resource-group $resourceGroup `
        --name $appName `
        --settings SCM_DO_BUILD_DURING_DEPLOYMENT=true `
            "APP_CORS_ORIGINS=https://$appName.azurewebsites.net,http://localhost:5173,http://127.0.0.1:5173" `
        --output none
    if ($LASTEXITCODE -ne 0) {
        throw "Azure App Service application settings failed with exit code $LASTEXITCODE."
    }

    & $az webapp update `
        --resource-group $resourceGroup `
        --name $appName `
        --https-only true `
        --output none
    if ($LASTEXITCODE -ne 0) {
        throw "Azure HTTPS-only configuration failed with exit code $LASTEXITCODE."
    }

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::Open(
        $zipPath,
        [System.IO.Compression.ZipArchiveMode]::Create
    )
    try {
        $entryNames = [System.Collections.Generic.HashSet[string]]::new()
        $files = @(
            Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot "app") -File -Recurse |
                Where-Object { $_.Extension -ne ".pyc" }
            Get-Item -LiteralPath (Join-Path $PSScriptRoot "requirements.txt")
        )
        foreach ($file in $files) {
            $relativePath = $file.FullName.Substring($PSScriptRoot.Length + 1)
            $entryName = $relativePath.Replace("\", "/")
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $archive,
                $file.FullName,
                $entryName,
                [System.IO.Compression.CompressionLevel]::Optimal
            ) | Out-Null
            [void]$entryNames.Add($entryName)
        }
        foreach ($requiredEntry in @("app/main.py", "app/__init__.py", "app/static/index.html", "requirements.txt")) {
            if (-not $entryNames.Contains($requiredEntry)) {
                throw "Deployment package is missing required path: $requiredEntry"
            }
        }
    } finally {
        $archive.Dispose()
    }

    & $az webapp deploy `
        --resource-group $resourceGroup `
        --name $appName `
        --src-path $zipPath `
        --type zip `
        --clean true `
        --restart true
    if ($LASTEXITCODE -ne 0) {
        throw "Azure App Service code deployment failed with exit code $LASTEXITCODE."
    }

    $healthUrl = "https://$appName.azurewebsites.net/healthz"
    $healthy = $false
    for ($attempt = 0; $attempt -lt 24; $attempt++) {
        Start-Sleep -Seconds 5
        try {
            $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 10
            if ($health.status -eq "ok" -and $health.azure_deployed) {
                $healthy = $true
                break
            }
        } catch {
        }
    }
    if (-not $healthy) {
        throw "Azure app did not pass its HTTPS health check: $healthUrl"
    }

    Write-Output "Deployment healthy: https://$appName.azurewebsites.net"
} finally {
    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    Pop-Location
}
