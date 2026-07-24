#requires -Version 5.1

<#
.SYNOPSIS
Builds the verified one-file Windows release of PL Analyzer Pro.

.DESCRIPTION
Runs the complete pytest and Ruff gates using the project virtual environment,
cleans only the exact project-local build and dist directories, builds the
selected locale targets with isolated PyInstaller work directories, performs
timed executable smoke tests, and writes dist\SHA256SUMS.txt.
#>

[CmdletBinding()]
param(
    [Parameter()]
    [ValidateSet("all", "en-US", "zh-CN")]
    [string]$Language = "all"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-NormalizedPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return [System.IO.Path]::GetFullPath($Path).TrimEnd([char[]]"\/")
}

function Assert-RequiredFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description is missing: $Path"
    }
}

function Remove-ExactBuildDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CandidatePath,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedPath,

        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot
    )

    $normalizedCandidate = Get-NormalizedPath -Path $CandidatePath
    $normalizedExpected = Get-NormalizedPath -Path $ExpectedPath
    $normalizedRoot = Get-NormalizedPath -Path $ProjectRoot

    if (-not [string]::Equals(
        $normalizedCandidate,
        $normalizedExpected,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Refusing to clean an unexpected path: $normalizedCandidate"
    }

    $candidateParent = Get-NormalizedPath -Path (
        [System.IO.Path]::GetDirectoryName($normalizedCandidate)
    )
    if (-not [string]::Equals(
        $candidateParent,
        $normalizedRoot,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Refusing to clean a directory outside the project root: $normalizedCandidate"
    }

    if (-not (Test-Path -LiteralPath $normalizedCandidate)) {
        return
    }

    $item = Get-Item -LiteralPath $normalizedCandidate -Force
    if (-not $item.PSIsContainer) {
        throw "Refusing to clean because the expected directory is a file: $normalizedCandidate"
    }
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing to clean a reparse-point directory: $normalizedCandidate"
    }

    Write-Host "Removing disposable build directory: $normalizedCandidate"
    Remove-Item -LiteralPath $normalizedCandidate -Recurse -Force
}

function Assert-LastCommandSucceeded {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Set-ProcessEnvironmentValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [AllowNull()]
        [string]$Value
    )

    [System.Environment]::SetEnvironmentVariable(
        $Name,
        $Value,
        [System.EnvironmentVariableTarget]::Process
    )
}

function Invoke-ExecutableSmokeTest {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter()]
        [int]$TimeoutMilliseconds = 45000
    )

    Assert-RequiredFile -Path $Path -Description "Smoke-test executable"
    $smokeVariableName = "PL_ANALYZER_PRO_SMOKE_EXIT_MS"
    $previousSmokeValue = [System.Environment]::GetEnvironmentVariable(
        $smokeVariableName,
        [System.EnvironmentVariableTarget]::Process
    )

    try {
        Set-ProcessEnvironmentValue -Name $smokeVariableName -Value "2000"
        $process = Start-Process `
            -FilePath $Path `
            -PassThru `
            -WindowStyle Hidden
        if (-not $process.WaitForExit($TimeoutMilliseconds)) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            $process.WaitForExit()
            throw "Executable smoke test timed out after $TimeoutMilliseconds ms: $Path"
        }
        if ($process.ExitCode -ne 0) {
            throw "Executable smoke test failed with exit code $($process.ExitCode): $Path"
        }
    }
    finally {
        Set-ProcessEnvironmentValue -Name $smokeVariableName -Value $previousSmokeValue
    }
}

$projectRoot = Get-NormalizedPath -Path $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$specPath = Join-Path $projectRoot "PLAnalyzerPro.spec"
$requirementsPath = Join-Path $projectRoot "requirements.txt"
$requirementsDevPath = Join-Path $projectRoot "requirements-dev.txt"
$configPath = Join-Path $projectRoot "config\default_settings.json"
$materialsPath = Join-Path $projectRoot "config\materials.json"
$buildDirectory = Join-Path $projectRoot "build"
$distDirectory = Join-Path $projectRoot "dist"
$manifestPath = Join-Path $distDirectory "SHA256SUMS.txt"
$buildLanguageVariableName = "PL_ANALYZER_PRO_BUILD_LANGUAGE"
$previousBuildLanguage = [System.Environment]::GetEnvironmentVariable(
    $buildLanguageVariableName,
    [System.EnvironmentVariableTarget]::Process
)

$selectedLanguages = switch ($Language) {
    "all" { @("en-US", "zh-CN") }
    "en-US" { @("en-US") }
    "zh-CN" { @("zh-CN") }
    default { throw "Unsupported release language: $Language" }
}

Assert-RequiredFile -Path $pythonPath -Description "Project virtual-environment Python"
Assert-RequiredFile -Path $specPath -Description "PyInstaller specification"
Assert-RequiredFile -Path $requirementsPath -Description "Runtime dependency manifest"
Assert-RequiredFile -Path $requirementsDevPath -Description "Development dependency manifest"
Assert-RequiredFile -Path $configPath -Description "Default application settings"
Assert-RequiredFile -Path $materialsPath -Description "Material database"

Push-Location -LiteralPath $projectRoot
try {
    $releaseVersion = (& $pythonPath -c "from core import __version__; print(__version__)").Trim()
    Assert-LastCommandSucceeded -Description "Release version lookup"
    if ($releaseVersion -notmatch "^\d+\.\d+\.\d+$") {
        throw "Release version must use MAJOR.MINOR.PATCH: $releaseVersion"
    }

    $targetMetadata = @{
        "en-US" = @{
            EntryPoint = Join-Path $projectRoot "main.py"
            VersionInfo = Join-Path $projectRoot "resources\version_info.txt"
        }
        "zh-CN" = @{
            EntryPoint = Join-Path $projectRoot "main_zh.py"
            VersionInfo = Join-Path $projectRoot "resources\version_info_zh_CN.txt"
        }
    }
    foreach ($buildLanguage in $selectedLanguages) {
        Assert-RequiredFile `
            -Path $targetMetadata[$buildLanguage].EntryPoint `
            -Description "$buildLanguage application entry point"
        Assert-RequiredFile `
            -Path $targetMetadata[$buildLanguage].VersionInfo `
            -Description "$buildLanguage Windows version resource"
    }

    Write-Host "[1/6] Running the complete test suite..."
    & $pythonPath -m pytest
    Assert-LastCommandSucceeded -Description "Test suite"

    Write-Host "[2/6] Running Ruff lint over the project..."
    & $pythonPath -m ruff check .
    Assert-LastCommandSucceeded -Description "Ruff lint"

    Write-Host "[3/6] Checking Ruff formatting..."
    & $pythonPath -m ruff format --check .
    Assert-LastCommandSucceeded -Description "Ruff format check"

    Write-Host "[4/6] Validating PyInstaller availability..."
    & $pythonPath -m PyInstaller --version
    Assert-LastCommandSucceeded -Description "PyInstaller availability check"

    Remove-ExactBuildDirectory `
        -CandidatePath $buildDirectory `
        -ExpectedPath (Join-Path $projectRoot "build") `
        -ProjectRoot $projectRoot
    Remove-ExactBuildDirectory `
        -CandidatePath $distDirectory `
        -ExpectedPath (Join-Path $projectRoot "dist") `
        -ProjectRoot $projectRoot

    Write-Host "[5/6] Building isolated one-file windowed executables..."
    $artifactPaths = @()
    foreach ($buildLanguage in $selectedLanguages) {
        $localeWorkDirectory = Join-Path $buildDirectory $buildLanguage
        Set-ProcessEnvironmentValue `
            -Name $buildLanguageVariableName `
            -Value $buildLanguage
        Write-Host "Building $buildLanguage..."
        & $pythonPath -m PyInstaller `
            --noconfirm `
            --clean `
            --distpath $distDirectory `
            --workpath $localeWorkDirectory `
            $specPath
        Assert-LastCommandSucceeded -Description "$buildLanguage PyInstaller build"

        $artifactName = (
            "PL-Analyzer-Pro-v{0}-Windows-x64-{1}.exe" -f
            $releaseVersion,
            $buildLanguage
        )
        $artifactPath = Join-Path $distDirectory $artifactName
        Assert-RequiredFile -Path $artifactPath -Description "$buildLanguage release executable"
        $artifactPaths += $artifactPath
    }

    $normalizedExpectedArtifacts = @(
        $artifactPaths | ForEach-Object { Get-NormalizedPath -Path $_ }
    )
    $unexpectedExecutables = @(
        Get-ChildItem -LiteralPath $distDirectory -Filter "*.exe" -File |
            Where-Object {
                (Get-NormalizedPath -Path $_.FullName) -notin $normalizedExpectedArtifacts
            }
    )
    if ($unexpectedExecutables.Count -gt 0) {
        $unexpectedNames = ($unexpectedExecutables.Name | Sort-Object) -join ", "
        throw "Unexpected executable found in the clean release directory: $unexpectedNames"
    }
    $actualExecutableCount = @(
        Get-ChildItem -LiteralPath $distDirectory -Filter "*.exe" -File
    ).Count
    if ($actualExecutableCount -ne $artifactPaths.Count) {
        throw (
            "Expected {0} executable(s), found {1}." -f
            $artifactPaths.Count,
            $actualExecutableCount
        )
    }

    Write-Host "[6/6] Running executable smoke tests and writing SHA-256 manifest..."
    foreach ($artifactPath in $artifactPaths) {
        Write-Host "Smoke testing $(Split-Path -Leaf $artifactPath)..."
        Invoke-ExecutableSmokeTest -Path $artifactPath
    }

    $hashLines = @(
        foreach ($artifactPath in ($artifactPaths | Sort-Object)) {
            $artifact = Get-Item -LiteralPath $artifactPath
            $hash = Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256
            "{0}  {1}" -f $hash.Hash.ToUpperInvariant(), $artifact.Name
        }
    )
    $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines(
        $manifestPath,
        [string[]]$hashLines,
        $utf8WithoutBom
    )
    Assert-RequiredFile -Path $manifestPath -Description "SHA-256 manifest"

    Write-Host ""
    Write-Host "Release build completed."
    foreach ($artifactPath in $artifactPaths) {
        $artifact = Get-Item -LiteralPath $artifactPath
        $hash = Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256
        Write-Host "Artifact: $($artifact.FullName)"
        Write-Host "Size: $($artifact.Length) bytes"
        Write-Host "SHA256: $($hash.Hash)"
    }
    Write-Host "Manifest: $manifestPath"
}
finally {
    Set-ProcessEnvironmentValue `
        -Name $buildLanguageVariableName `
        -Value $previousBuildLanguage
    Pop-Location
}
