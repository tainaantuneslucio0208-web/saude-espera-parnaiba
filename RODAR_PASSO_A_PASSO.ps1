#Requires -Version 5.1
<#
.SYNOPSIS
    Guia passo a passo (com comandos) para rodar o projeto: backend + MySQL + importação + uvicorn.

.DESCRIPTION
    Execute na raiz do projeto (clique direito no arquivo -> "Executar com PowerShell"),
    ou no PowerShell:
        cd "C:\caminho\para\saude-espera-parnaiba"
        Set-ExecutionPolicy -Scope CurrentUser RemoteSigned   # só se pedir permissão
        .\RODAR_PASSO_A_PASSO.ps1

    Parâmetros opcionais:
        .\RODAR_PASSO_A_PASSO.ps1 -ExcelPath "D:\dados\planilha.xlsx" -Port 8000 -SkipVenv
#>
param(
    [string]$ExcelPath = $(Join-Path $env:USERPROFILE "Downloads\Tempo de Espera x Atendimento 1.xlsx"),
    [int]$Port = 8000,
    [switch]$SkipVenv
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$Backend = Join-Path $ProjectRoot "backend"
$DatabaseDir = Join-Path $ProjectRoot "database"
$SchemaFile = Join-Path $DatabaseDir "schema.sql"

function Write-Step($n, $title) {
    Write-Host ""
    Write-Host "========== PASSO $n : $title ==========" -ForegroundColor Cyan
}

function Pause-Step($msg) {
    Write-Host $msg -ForegroundColor Yellow
    Read-Host "Pressione ENTER para continuar"
}

Write-Host ""
Write-Host "PROJETO: Motor de busca / apoio à decisão (tempo de espera)" -ForegroundColor Green
Write-Host "Pasta do projeto: $ProjectRoot"
Write-Host ""

# --- Passo 1 ---
Write-Step 1 "Conferir Python"
try {
    $ver = python --version 2>&1
    Write-Host "OK: $ver"
}
catch {
    Write-Host "ERRO: Python não encontrado. Instale em https://www.python.org e marque 'Add to PATH'." -ForegroundColor Red
    exit 1
}

# --- Passo 2 ---
Write-Step 2 "Ambiente virtual (recomendado)"
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not $SkipVenv) {
    if (-not (Test-Path $VenvPython)) {
        Write-Host "Criando .venv em $ProjectRoot ..."
        Set-Location $ProjectRoot
        python -m venv .venv
    }
    Write-Host "Ativando .venv ..."
    $activate = Join-Path $ProjectRoot ".venv\Scripts\Activate.ps1"
    if (Test-Path $activate) {
        . $activate
    }
    $pythonCmd = "python"
}
else {
    Write-Host "Pulando venv (SkipVenv). Usando python do PATH."
    $pythonCmd = "python"
}

# Garantir que os próximos comandos usem o mesmo Python
Set-Location $Backend
$py = & python -c "import sys; print(sys.executable)" 2>&1
Write-Host "Python em uso: $py"

# --- Passo 3 ---
Write-Step 3 "Instalar dependências (inclui cryptography para MySQL 8)"
python -m pip install --upgrade pip
python -m pip install -r (Join-Path $Backend "requirements.txt")
python -c "import cryptography; print('cryptography OK:', cryptography.__version__)"

# --- Passo 4 ---
Write-Step 4 "Arquivo .env (MySQL)"
$envFile = Join-Path $Backend ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $Backend ".env.example") $envFile -ErrorAction SilentlyContinue
}
if (Test-Path $envFile) {
    Write-Host "Conteúdo de .env (revise porta/usuário se necessário):"
    Get-Content $envFile | ForEach-Object { Write-Host "  $_" }
}
else {
    Write-Host "AVISO: crie backend\.env com MYSQL_HOST, MYSQL_PORT (geralmente 3306), MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE." -ForegroundColor Yellow
}

Pause-Step @"
Antes de testar a porta do MySQL e importar a planilha, no MySQL Workbench (como administrador, ex.: root):
  1) Abra e execute o arquivo: $SchemaFile
  2) Depois execute:
     CREATE USER IF NOT EXISTS 'saude'@'localhost' IDENTIFIED BY 'saude123';
     GRANT ALL PRIVILEGES ON saude_parnaiba.* TO 'saude'@'localhost';
     FLUSH PRIVILEGES;
  (Se der erro no CREATE USER por versão antiga, use CREATE USER sem IF NOT EXISTS.)
"@

# --- Passo 5 ---
Write-Step 5 "Testar porta do MySQL (ajuste MYSQL_PORT no .env se falhar)"
$portLine = Get-Content $envFile -ErrorAction SilentlyContinue | Where-Object { $_ -match "^\s*MYSQL_PORT\s*=" }
$mysqlPort = 3306
if ($portLine -match "=\s*(\d+)") { $mysqlPort = [int]$Matches[1] }
Write-Host "Testando 127.0.0.1:$mysqlPort ..."
$t = Test-NetConnection -ComputerName 127.0.0.1 -Port $mysqlPort -WarningAction SilentlyContinue
if ($t.TcpTestSucceeded) {
    Write-Host "OK: MySQL parece estar escutando na porta $mysqlPort." -ForegroundColor Green
}
else {
    Write-Host "AVISO: não consegui conectar na porta $mysqlPort. Verifique o serviço MySQL no Windows (services.msc)." -ForegroundColor Yellow
}

# --- Passo 6 ---
Write-Step 6 "Importar Excel para o MySQL"
if (-not (Test-Path $ExcelPath)) {
    Write-Host "ERRO: Arquivo Excel não encontrado: $ExcelPath" -ForegroundColor Red
    Write-Host "Chame o script assim: .\RODAR_PASSO_A_PASSO.ps1 -ExcelPath `"C:\caminho\arquivo.xlsx`"" -ForegroundColor Yellow
    exit 1
}
Write-Host "Usando planilha: $ExcelPath"
Set-Location $Backend
python scripts\import_excel.py --file $ExcelPath --truncate

# --- Passo 7 ---
Write-Step 7 "Subir o servidor (uvicorn)"
Write-Host "Se a porta $Port estiver em uso, altere: -Port 8001" -ForegroundColor Yellow
Write-Host ""
Write-Host "Abrindo NOVA janela do PowerShell com o servidor..." -ForegroundColor Cyan
$pythonForServer = "python"
if ((-not $SkipVenv) -and (Test-Path $VenvPython)) {
    $pythonForServer = "`"$VenvPython`""
}
$uvicornCmd = @"
cd `"$Backend`"
Write-Host "Servidor: http://127.0.0.1:$Port  |  Docs: http://127.0.0.1:$Port/docs" -ForegroundColor Green
& $pythonForServer -m uvicorn app.main:app --reload --host 127.0.0.1 --port $Port
"@
Start-Process powershell.exe -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $uvicornCmd)

Start-Sleep -Seconds 2

# --- Passo 8 ---
Write-Step 8 "Teste rápido da API (pode falhar se o servidor ainda estiver iniciando — rode de novo em alguns segundos)"
try {
    $health = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 15
    Write-Host ($health | ConvertTo-Json -Compress) -ForegroundColor Green
}
catch {
    Write-Host "Ainda não respondeu ou erro: $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host "Espere o uvicorn terminar de subir e execute manualmente:" -ForegroundColor Yellow
    Write-Host "  Invoke-RestMethod `"http://127.0.0.1:$Port/api/health`"" -ForegroundColor White
}

Write-Host ""
Write-Host "PRONTO." -ForegroundColor Green
Write-Host "  - Site:  http://127.0.0.1:$Port/"
Write-Host "  - API:   http://127.0.0.1:$Port/docs"
Write-Host "  - Saúde: http://127.0.0.1:$Port/api/health"
Write-Host ""
Write-Host "Mantenha a janela do uvicorn ABERTA enquanto usar o sistema." -ForegroundColor Yellow
Write-Host ""
