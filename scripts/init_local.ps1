<# NewsIntentRec 演示环境的一键式本地初始化脚本。 #>
[CmdletBinding()]
param(
    [string]$Python = 'C:\ProgramData\anaconda3\python.exe',
    [string]$DatabaseUrl = 'mysql+pymysql://root:root@localhost:3307/newsrec_demo',
    [int]$BackendPort = 8000,
    [int]$ProductFrontendPort = 5174,
    [int]$MysqlHealthTimeoutSeconds = 120,
    [int]$ConsumerMetricsPort = 9101,
    [int]$OutboxMetricsPort = 9102,
    [switch]$SkipBackend,
    [switch]$ProductFrontend,
    [switch]$WithKafka,
    [ValidateSet('kafka_dual_write', 'kafka_async')]
    [string]$EventMode = 'kafka_dual_write',
    [switch]$SmokeTest
)

$ErrorActionPreference = 'Stop'
if (-not $PSBoundParameters.ContainsKey('DatabaseUrl')) {
    $DatabaseUrl = 'mysql+pymysql://root:root@localhost:3307/newsrec_demo'
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtimeDir = Join-Path $repoRoot '.runtime\init_local'
$startedProcesses = New-Object System.Collections.Generic.List[object]

function Write-Step {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Cyan
}

function Invoke-External {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$Label
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

function Test-ListeningPort {
    param([int]$Port)
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    return $listeners.Count -gt 0
}

function Wait-MysqlHealthy {
    param([int]$TimeoutSeconds)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $status = (& docker inspect -f '{{.State.Health.Status}}' newsrec-mysql 2>$null)
        if ($LASTEXITCODE -ne 0) {
            $status = ''
        }
        if ($status -eq 'healthy') {
            Write-Host '  MySQL is healthy' -ForegroundColor Green
            return
        }
        Write-Host "  mysql health: $status"
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)

    throw "MySQL did not become healthy within $TimeoutSeconds seconds"
}

function Wait-KafkaHealthy {
    param([int]$TimeoutSeconds)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $status = (& docker inspect -f '{{.State.Health.Status}}' newsrec-kafka 2>$null)
        if ($LASTEXITCODE -ne 0) {
            $status = ''
        }
        if ($status -eq 'healthy') {
            Write-Host '  Kafka is healthy' -ForegroundColor Green
            return
        }
        Write-Host "  kafka health: $status"
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)

    throw "Kafka did not become healthy within $TimeoutSeconds seconds"
}

function Start-LocalService {
    param(
        [string]$Name,
        [string[]]$Arguments,
        [int]$Port
    )

    if (Test-ListeningPort -Port $Port) {
        throw "$Name port $Port is already in use. Stop the existing service or choose another port."
    }

    $stdout = Join-Path $runtimeDir "$Name.out.log"
    $stderr = Join-Path $runtimeDir "$Name.err.log"
    Remove-Item -LiteralPath $stdout, $stderr -Force -ErrorAction SilentlyContinue

    $process = Start-Process `
        -FilePath $Python `
        -ArgumentList $Arguments `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden `
        -PassThru

    Start-Sleep -Seconds 1
    if ($process.HasExited) {
        $errText = ''
        if (Test-Path $stderr) {
            $errText = (Get-Content $stderr -ErrorAction SilentlyContinue | Select-Object -Last 20) -join [Environment]::NewLine
        }
        throw "$Name exited during startup. See $stderr. $errText"
    }

    $entry = [pscustomobject]@{
        Name = $Name
        Process = $process
        Port = $Port
        Stdout = $stdout
        Stderr = $stderr
    }
    $startedProcesses.Add($entry) | Out-Null
    Write-Host "  $Name pid=$($process.Id) url=http://127.0.0.1:$Port"
    Write-Host "  logs: $stdout ; $stderr"
}

function Stop-StartedProcesses {
    foreach ($entry in $startedProcesses) {
        try {
            if (-not $entry.Process.HasExited) {
                Stop-Process -Id $entry.Process.Id -Force -ErrorAction SilentlyContinue
                Write-Host "  stopped $($entry.Name) pid=$($entry.Process.Id)"
            }
        } catch {
            Write-Warning "Could not stop $($entry.Name): $($_.Exception.Message)"
        }
    }
}

function Wait-JsonEndpoint {
    param(
        [string]$Name,
        [string]$Url,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-RestMethod -Uri $Url -TimeoutSec 3
            Write-Host "  $Name OK" -ForegroundColor Green
            return $response
        } catch {
            Start-Sleep -Seconds 1
        }
    } while ((Get-Date) -lt $deadline)

    throw "$Name did not respond at $Url within $TimeoutSeconds seconds"
}

function Wait-HttpEndpoint {
    param(
        [string]$Name,
        [string]$Url,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -lt 400) {
                Write-Host "  $Name OK" -ForegroundColor Green
                return
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    } while ((Get-Date) -lt $deadline)

    throw "$Name did not respond at $Url within $TimeoutSeconds seconds"
}

Set-Location $repoRoot
New-Item -ItemType Directory -Force $runtimeDir | Out-Null

Write-Step '[1/6] Checking prerequisites'
if (($Python.Contains('\') -or $Python.Contains(':')) -and -not (Test-Path $Python)) {
    throw "Python executable not found: $Python"
}
Invoke-External -FilePath $Python -Arguments @('--version') -Label 'Python check'
Invoke-External -FilePath 'docker' -Arguments @('--version') -Label 'Docker check'
Invoke-External -FilePath 'docker' -Arguments @('compose', 'version') -Label 'Docker Compose check'

Write-Step '[2/6] Starting MySQL via docker compose'
Invoke-External -FilePath 'docker' -Arguments @('compose', 'up', '-d') -Label 'docker compose up'
Wait-MysqlHealthy -TimeoutSeconds $MysqlHealthTimeoutSeconds

if ($WithKafka) {
    Write-Step '[2.5/6] Starting Kafka via docker compose'
    Invoke-External `
        -FilePath 'docker' `
        -Arguments @('compose', '-f', 'docker-compose.kafka.yml', 'up', '-d') `
        -Label 'docker compose kafka up'
    Wait-KafkaHealthy -TimeoutSeconds $MysqlHealthTimeoutSeconds
    $env:NEWSREC_EVENT_MODE = $EventMode
    $env:NEWSREC_KAFKA_BOOTSTRAP_SERVERS = '127.0.0.1:9092'
} else {
    $env:NEWSREC_EVENT_MODE = 'sync_mysql'
}

Write-Step '[3/6] Setting NEWSREC_DATABASE_URL for child processes'
$env:NEWSREC_DATABASE_URL = $DatabaseUrl
$env:NEWSREC_DEMO_SEED_DIR = 'build/mind_demo_world'
$env:NEWSREC_SPONSORED_ENABLED = '1'

Write-Step '[4/6] Applying schema and demo seed'
Invoke-External -FilePath $Python -Arguments @('scripts\apply_demo_mysql.py') -Label 'apply_demo_mysql.py'

Write-Step '[5/6] Resetting demo user profile'
Invoke-External -FilePath $Python -Arguments @('scripts\reset_demo_user.py') -Label 'reset_demo_user.py'

Write-Step '[6/6] Launching services'
try {
    if (-not $SkipBackend) {
        Start-LocalService `
            -Name 'backend' `
            -Arguments @('-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', "$BackendPort") `
            -Port $BackendPort
    }

    if ($WithKafka) {
        Start-LocalService `
            -Name 'outbox' `
            -Arguments @('scripts\run_outbox_publisher.py') `
            -Port $OutboxMetricsPort
        Start-LocalService `
            -Name 'consumer' `
            -Arguments @('scripts\run_profile_consumer.py') `
            -Port $ConsumerMetricsPort
    }

    if ($ProductFrontend) {
        $pfDir = Join-Path $repoRoot 'product-frontend'
        if (-not (Test-Path (Join-Path $pfDir 'node_modules'))) {
            Write-Step 'Installing product frontend dependencies'
            Push-Location $pfDir
            try {
                Invoke-External -FilePath 'npm' -Arguments @('ci') -Label 'npm ci'
            } finally {
                Pop-Location
            }
        }

        if (Test-ListeningPort -Port $ProductFrontendPort) {
            throw "Product frontend port $ProductFrontendPort is already in use."
        }

        $pfStdout = Join-Path $runtimeDir 'product-frontend.out.log'
        $pfStderr = Join-Path $runtimeDir 'product-frontend.err.log'
        Remove-Item -LiteralPath $pfStdout, $pfStderr -Force -ErrorAction SilentlyContinue

        $pfProcess = Start-Process `
            -FilePath (Get-Command npx.cmd -ErrorAction Stop).Source `
            -ArgumentList @('vite', '--host', '127.0.0.1', '--port', "$ProductFrontendPort") `
            -WorkingDirectory $pfDir `
            -RedirectStandardOutput $pfStdout `
            -RedirectStandardError $pfStderr `
            -WindowStyle Hidden `
            -PassThru

        Start-Sleep -Seconds 3
        if ($pfProcess.HasExited) {
            $errText = ''
            if (Test-Path $pfStderr) {
                $errText = (Get-Content $pfStderr -ErrorAction SilentlyContinue | Select-Object -Last 20) -join [Environment]::NewLine
            }
            throw "Product frontend exited during startup. $errText"
        }

        $entry = [pscustomobject]@{
            Name = 'product-frontend'
            Process = $pfProcess
            Port = $ProductFrontendPort
            Stdout = $pfStdout
            Stderr = $pfStderr
        }
        $startedProcesses.Add($entry) | Out-Null
        Write-Host "  product-frontend pid=$($pfProcess.Id) url=http://127.0.0.1:$ProductFrontendPort"
    }

    if (-not $SkipBackend) {
        $health = Wait-JsonEndpoint -Name 'Backend health' -Url "http://127.0.0.1:$BackendPort/healthz"
        Write-Host "  repository_backend=$($health.repository_backend)"
        Invoke-External `
            -FilePath $Python `
            -Arguments @('scripts\smoke_local.py', '--base-url', "http://127.0.0.1:$BackendPort") `
            -Label 'smoke_local.py'
    }

    if ($ProductFrontend) {
        Wait-HttpEndpoint -Name 'Product frontend' -Url "http://127.0.0.1:$ProductFrontendPort/"
    }

    Write-Host ''
    Write-Host 'Ready.' -ForegroundColor Green
    if (-not $SkipBackend) {
        Write-Host "  Backend:          http://127.0.0.1:$BackendPort"
    }
    if ($ProductFrontend) {
        Write-Host "  Product frontend: http://127.0.0.1:$ProductFrontendPort"
    }
    Write-Host "  MySQL:            $DatabaseUrl"

    if ($SmokeTest) {
        Write-Host 'Smoke test passed. Stopping backend/frontend started by this script.' -ForegroundColor Green
    } else {
        Write-Host 'Press Ctrl+C to stop backend/frontend. MySQL is left running; use docker compose down to stop it.' -ForegroundColor Yellow
        while ($startedProcesses.Count -gt 0) {
            foreach ($entry in $startedProcesses) {
                if ($entry.Process.HasExited) {
                    throw "$($entry.Name) exited with code $($entry.Process.ExitCode). See $($entry.Stderr)."
                }
            }
            Start-Sleep -Seconds 2
        }
    }
} finally {
    if ($SmokeTest) {
        Stop-StartedProcesses
    } elseif ($startedProcesses.Count -gt 0) {
        Stop-StartedProcesses
    }
}
