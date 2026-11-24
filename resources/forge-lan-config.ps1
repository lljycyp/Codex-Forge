param([switch]$Restore)

$ErrorActionPreference = 'Stop'
$utf8 = [Text.UTF8Encoding]::new($false)
if ($Restore) { [Console]::OutputEncoding = $utf8 }
$caVariable = 'CODEX_CA_CERTIFICATE'
$userScope = [EnvironmentVariableTarget]::User
$codexHome = [Environment]::GetEnvironmentVariable('CODEX_HOME', $userScope)
if (!$codexHome) { $codexHome = $env:CODEX_HOME }
if (!$codexHome) { $codexHome = Join-Path $env:USERPROFILE '.codex' }
$codexHome = [IO.Path]::GetFullPath($codexHome)
$stateDir = Join-Path $codexHome 'forge-lan'
$statePath = Join-Path $stateDir 'settings.json'
$installedCa = Join-Path $stateDir 'forge-gateway-ca.pem'
$codex = $null
$lock = $null
$rpcId = 0

function Invoke-CodexRpc($Method, $Parameters, [switch]$Notification) {
    $request = @{ method = $Method; params = $Parameters }
    if (!$Notification) { $request.id = ++$script:rpcId }
    $codex.StandardInput.WriteLine(($request | ConvertTo-Json -Compress -Depth 8))
    $codex.StandardInput.Flush()
    if ($Notification) { return }

    $timeout = [Diagnostics.Stopwatch]::StartNew()
    while ($timeout.ElapsedMilliseconds -lt 15000) {
        $line = $codex.StandardOutput.ReadLineAsync()
        if (!$line.Wait([int][Math]::Max(1, 15000 - $timeout.ElapsedMilliseconds))) { break }
        if ($null -eq $line.Result) { throw 'Codex 配置进程已退出。' }
        $response = $rpcJson.DeserializeObject($line.Result)
        if ($response.id -ne $request.id) { continue }
        if ($response.error) {
            throw "Codex 无法完成配置操作 $Method（$($response.error.code)）。请检查配置或更新 Codex。"
        }
        return $response.result
    }
    throw "Codex 配置操作 $Method 超时。"
}

function Set-GatewayAddress($Value, $Layer) {
    $result = Invoke-CodexRpc 'config/value/write' @{
        keyPath = 'openai_base_url'
        value = $Value
        mergeStrategy = 'replace'
        expectedVersion = $Layer.version
    }
    if ($result.status -eq 'okOverridden') {
        throw '当前网关地址被其他配置覆盖。请先处理覆盖项，再执行恢复或重新配置。'
    }
}

try {
    if ($Restore -and !(Test-Path -LiteralPath $statePath)) {
        Write-Host '当前用户没有需要恢复的 Forge 网关配置。'
        exit 0
    }
    if (Get-Process -Name 'ChatGPT', 'Codex' -ErrorAction SilentlyContinue) {
        throw '请完全退出 Codex（包括后台进程），然后重新运行此配置工具。'
    }
    $package = Get-AppxPackage -Name OpenAI.Codex | Select-Object -First 1
    if (!$package) { throw '未找到当前用户安装的原版 Windows Codex 桌面端。' }
    $executable = Join-Path $package.InstallLocation 'app\resources\codex.exe'
    if (!(Test-Path -LiteralPath $executable -PathType Leaf)) {
        throw '找不到 Codex 的配置程序，请更新或重新安装原版 Codex。'
    }

    [IO.Directory]::CreateDirectory($stateDir) | Out-Null
    $lock = [IO.File]::Open((Join-Path $stateDir 'settings.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $start = [Diagnostics.ProcessStartInfo]::new($executable, 'app-server -c analytics.enabled=false')
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardOutputEncoding = $utf8
    $start.EnvironmentVariables['CODEX_HOME'] = $codexHome
    # Windows PowerShell uses the console input encoding for redirected stdin.
    [Console]::InputEncoding = $utf8
    # Codex project keys can differ only in case, which ConvertFrom-Json rejects.
    Add-Type -AssemblyName System.Web.Extensions
    $rpcJson = [System.Web.Script.Serialization.JavaScriptSerializer]::new()
    $rpcJson.MaxJsonLength = [int]::MaxValue
    $codex = [Diagnostics.Process]::Start($start)
    [void]$codex.StandardError.ReadToEndAsync()
    Invoke-CodexRpc 'initialize' @{ clientInfo = @{ name = 'codex-forge-lan-config'; version = '1' } } | Out-Null
    Invoke-CodexRpc 'initialized' @{} -Notification

    $settings = Invoke-CodexRpc 'config/read' @{ includeLayers = $true }
    $userLayer = $settings.layers | Where-Object { $_.name.type -eq 'user' -and !$_.name.profile } | Select-Object -First 1
    $currentUrl = $userLayer.config.openai_base_url
    $currentCa = [Environment]::GetEnvironmentVariable($caVariable, $userScope)
    $state = $null
    if (Test-Path -LiteralPath $statePath) {
        $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if (($currentUrl -cne $state.baseUrl -and $currentUrl -cne $state.previousUrl) -or
            ($currentCa -ine $installedCa -and $currentCa -ine $state.previousCa)) {
            throw 'Codex 的网关地址或证书设置已被其他操作修改，请先核对现有设置。'
        }
    }

    if ($Restore) {
        $account = Invoke-CodexRpc 'account/read' @{ refreshToken = $false }
        if ($account.account.type -eq 'apiKey') {
            throw '请先打开 Codex 退出 API Key 登录，再完全关闭 Codex 并运行恢复工具。'
        }
        if ($currentUrl -cne $state.previousUrl) { Set-GatewayAddress $state.previousUrl $userLayer }
        [Environment]::SetEnvironmentVariable($caVariable, $state.previousCa, $userScope)
        if ($state.previousCa -ine $installedCa -and (Test-Path -LiteralPath $installedCa)) {
            Remove-Item -LiteralPath $installedCa
        }
        Remove-Item -LiteralPath $statePath
        Write-Host '已恢复 Codex 原有网关设置。可以照常打开 Codex 登录。'
        exit 0
    }

    $manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'gateway.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $baseUrl = [string]$manifest.baseUrl
    $endpoint = [Uri]$baseUrl
    if (!$endpoint.IsAbsoluteUri -or $endpoint.Scheme -ne 'https' -or $endpoint.HostNameType -ne 'IPv4' -or
        $endpoint.AbsolutePath -ne '/v1' -or $endpoint.UserInfo -or $endpoint.Query -or $endpoint.Fragment) {
        throw '配置包中的网关地址无效，请从 Forge 重新导出。'
    }
    $packageCa = Join-Path $PSScriptRoot 'forge-gateway-ca.pem'
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $certificateHash = [Convert]::ToBase64String($sha.ComputeHash([IO.File]::ReadAllBytes($packageCa))) }
    finally { $sha.Dispose() }
    if ($state -and ($state.baseUrl -cne $baseUrl -or $state.certificateHash -cne $certificateHash)) {
        throw '当前用户已配置另一台 Forge 网关或另一份证书。请先恢复原设置，再应用新配置包。'
    }
    if ($settings.config.model_provider -and $settings.config.model_provider -cne 'openai') {
        throw '当前 Codex 使用自定义模型提供方。请先在 Codex 切回默认 OpenAI 提供方。'
    }
    $overrides = @($settings.layers | Where-Object {
        $_.name.type -ne 'user' -or $_.name.profile
    } | ForEach-Object { $_.config.openai_base_url })
    $overrides += @($env:OPENAI_BASE_URL, $env:CODEX_APP_SERVER_OPENAI_BASE_URL)
    if (@($overrides | Where-Object { $_ -and $_ -cne $baseUrl }).Count) {
        throw '发现其他 Codex 网关地址覆盖项，请先恢复默认地址。'
    }
    if (!$state -and (($currentUrl -and $currentUrl -cne $baseUrl) -or
        (@($currentCa, $env:CODEX_CA_CERTIFICATE, $env:SSL_CERT_FILE) | Where-Object { $_ -and $_ -ine $installedCa }))) {
        throw '发现已有的 Codex 网关或 CA 配置，请先核对现有设置。'
    }

    $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
    # The private Forge CA has no revocation endpoint. The CA and host are still verified.
    $curlArgs = @('--silent', '--show-error', '--head', '--noproxy', '*', '--connect-timeout', '4',
        '--max-time', '8', '--ssl-revoke-best-effort', '--cacert', $packageCa,
        '--output', 'NUL', '--write-out', '%{http_code}', "$baseUrl/models")
    $status = & $curl @curlArgs
    if ($LASTEXITCODE -ne 0 -or $status -ne '401') {
        throw "无法通过 HTTPS 验证 $baseUrl。请确认 Forge 正在共享，且现在位于同一局域网。"
    }

    if (!$state) {
        $state = @{
            baseUrl = $baseUrl; certificateHash = $certificateHash
            previousUrl = $currentUrl; previousCa = $currentCa
        }
        $pending = Join-Path $stateDir 'settings.pending.json'
        [IO.File]::WriteAllText($pending, ($state | ConvertTo-Json), $utf8)
        [IO.File]::Move($pending, $statePath)
        $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    Copy-Item -LiteralPath $packageCa -Destination $installedCa -Force
    try {
        [Environment]::SetEnvironmentVariable($caVariable, $installedCa, $userScope)
        if ($currentUrl -cne $baseUrl) { Set-GatewayAddress $baseUrl $userLayer }
    } catch {
        [Environment]::SetEnvironmentVariable($caVariable, $state.previousCa, $userScope)
        throw
    }
    Write-Host "已配置 Forge 网关 $baseUrl。"
    Write-Host '照常打开原版 Codex，选择 API Key 登录并粘贴管理员发给你的个人 Key。'
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    if ($codex) {
        if (!$codex.HasExited) {
            $codex.StandardInput.Close()
            if (!$codex.WaitForExit(2500)) { $codex.Kill(); $codex.WaitForExit() }
        }
        $codex.Dispose()
    }
    if ($lock) { $lock.Dispose() }
}
