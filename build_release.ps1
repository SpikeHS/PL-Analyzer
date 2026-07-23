#requires -Version 5.1

<#
.SYNOPSIS
Builds the verified one-file Windows release of PL Analyzer Pro.

.DESCRIPTION
Runs the complete pytest and Ruff gates using the project virtual environment,
cleans only the exact project-local build and dist directories, then invokes
PyInstaller with PLAnalyzerPro.spec. The resulting executable is:
dist\PL Analyzer Pro.exe
#>

[CmdletBinding()]
param()

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

$projectRoot = Get-NormalizedPath -Path $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$specPath = Join-Path $projectRoot "PLAnalyzerPro.spec"
$mainPath = Join-Path $projectRoot "main.py"
$requirementsPath = Join-Path $projectRoot "requirements.txt"
$requirementsDevPath = Join-Path $projectRoot "requirements-dev.txt"
$configPath = Join-Path $projectRoot "config\default_settings.json"
$materialsPath = Join-Path $projectRoot "config\materials.json"
$versionInfoPath = Join-Path $projectRoot "resources\version_info.txt"
$buildDirectory = Join-Path $projectRoot "build"
$distDirectory = Join-Path $projectRoot "dist"
$artifactPath = Join-Path $distDirectory "PL Analyzer Pro.exe"

Assert-RequiredFile -Path $pythonPath -Description "Project virtual-environment Python"
Assert-RequiredFile -Path $specPath -Description "PyInstaller specification"
Assert-RequiredFile -Path $mainPath -Description "Application entry point"
Assert-RequiredFile -Path $requirementsPath -Description "Runtime dependency manifest"
Assert-RequiredFile -Path $requirementsDevPath -Description "Development dependency manifest"
Assert-RequiredFile -Path $configPath -Description "Default application settings"
Assert-RequiredFile -Path $materialsPath -Description "Material database"
Assert-RequiredFile -Path $versionInfoPath -Description "Windows version resource"

Push-Location -LiteralPath $projectRoot
try {
    Write-Host "[1/4] Running the complete test suite..."
    & $pythonPath -m pytest
    Assert-LastCommandSucceeded -Description "Test suite"

    Write-Host "[2/4] Running Ruff over the project..."
    & $pythonPath -m ruff check .
    Assert-LastCommandSucceeded -Description "Ruff"

    Write-Host "[3/4] Validating PyInstaller availability..."
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

    Write-Host "[4/4] Building the one-file windowed executable..."
    & $pythonPath -m PyInstaller `
        --noconfirm `
        --clean `
        --distpath $distDirectory `
        --workpath $buildDirectory `
        $specPath
    Assert-LastCommandSucceeded -Description "PyInstaller build"

    Assert-RequiredFile -Path $artifactPath -Description "Release executable"
    $unexpectedExecutables = @(
        Get-ChildItem -LiteralPath $distDirectory -Filter "*.exe" -File |
            Where-Object {
                -not [string]::Equals(
                    (Get-NormalizedPath -Path $_.FullName),
                    (Get-NormalizedPath -Path $artifactPath),
                    [System.StringComparison]::OrdinalIgnoreCase
                )
            }
    )
    if ($unexpectedExecutables.Count -gt 0) {
        throw "Unexpected executable found in the clean release directory."
    }

    $artifact = Get-Item -LiteralPath $artifactPath
    $hash = Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256
    Write-Host ""
    Write-Host "Release build completed."
    Write-Host "Artifact: $($artifact.FullName)"
    Write-Host "Size: $($artifact.Length) bytes"
    Write-Host "SHA256: $($hash.Hash)"
}
finally {
    Pop-Location
}
