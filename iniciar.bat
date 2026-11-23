@echo off
REM Arranca ShopBot con doble clic. Crea el venv si falta, instala dependencias,
REM verifica Ollama y el modelo, y abre la app.
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo Falta Python 3. Instalalo desde https://www.python.org y marca "Add to PATH".
  pause & exit /b 1
)

if not exist venv\Scripts\python.exe (
  echo ^>^> Creando entorno virtual...
  python -m venv venv
  if errorlevel 1 ( echo Fallo la creacion del venv. & pause & exit /b 1 )
)
call venv\Scripts\activate.bat
if not exist venv\.deps_ok (
  echo ^>^> Instalando dependencias ^(solo la primera vez^)...
  pip install -q -r requirements.txt
  if errorlevel 1 ( echo Fallo la instalacion de dependencias. & pause & exit /b 1 )
  echo ok> venv\.deps_ok
)

if not exist .env (
  if exist .env.example ( copy .env.example .env >nul ) else ( echo MODELO=llama3.2> .env )
)
set "MODELO=llama3.2"
for /f "tokens=1,* delims==" %%a in ('findstr /b "MODELO=" .env') do set "MODELO=%%b"

where ollama >nul 2>&1
if errorlevel 1 (
  echo Falta Ollama. Instalalo desde https://ollama.com y volve a abrir este archivo.
  pause & exit /b 1
)

curl -s http://localhost:11434 >nul 2>&1
if not errorlevel 1 goto ollama_ok
echo ^>^> Iniciando Ollama...
start "Ollama" /min ollama serve
set /a intentos=0
:esperar
timeout /t 1 >nul
set /a intentos+=1
curl -s http://localhost:11434 >nul 2>&1
if not errorlevel 1 goto ollama_ok
if %intentos% lss 20 goto esperar
echo Ollama no arranco. Abrilo a mano y volve a probar.
pause & exit /b 1
:ollama_ok

ollama list | findstr /b /c:"%MODELO%" >nul
if errorlevel 1 (
  echo ^>^> Bajando el modelo %MODELO% ^(puede tardar unos minutos^)...
  ollama pull %MODELO%
)

if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  mkdir "%USERPROFILE%\.streamlit" 2>nul
  ( echo [general] & echo email = "" ) > "%USERPROFILE%\.streamlit\credentials.toml"
)

echo ^>^> Listo. Abriendo ShopBot en http://localhost:8501  ^(Ctrl+C para cerrar^)
python -m streamlit run src\streamlit_chatbot.py
pause
