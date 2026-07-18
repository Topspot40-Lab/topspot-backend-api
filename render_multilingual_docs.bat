@echo off
setlocal

cd /d %~dp0

echo ================================================================
echo TopSpot Studio - Multilingual Documentary Factory
echo ================================================================
echo.

echo ================================================================
echo Ed Sullivan
echo ================================================================
.venv\Scripts\python -m backend.studio.build_review_package --docuseries-id 33 --all-languages
if errorlevel 1 goto :error

echo.
echo ================================================================
echo Dick Clark
echo ================================================================
.venv\Scripts\python -m backend.studio.build_review_package --docuseries-id 34 --all-languages
if errorlevel 1 goto :error

echo.
echo ================================================================
echo Johnny Cash
echo ================================================================
.venv\Scripts\python -m backend.studio.build_review_package --artist-id 141 --all-languages
if errorlevel 1 goto :error

echo.
echo ================================================================
echo Casey Kasem
echo ================================================================
.venv\Scripts\python -m backend.studio.build_review_package --docuseries-id 36 --all-languages
if errorlevel 1 goto :error

echo.
echo ================================================================
echo Juan Gabriel
echo ================================================================
.venv\Scripts\python -m backend.studio.build_review_package --artist-id 1952 --all-languages
if errorlevel 1 goto :error

echo.
echo ================================================================
echo Luis Miguel
echo ================================================================
.venv\Scripts\python -m backend.studio.build_review_package --artist-id 777 --all-languages
if errorlevel 1 goto :error

echo.
echo ================================================================
echo ALL DOCUMENTARIES COMPLETED SUCCESSFULLY
echo ================================================================
pause
exit /b 0

:error
echo.
echo ********************************************************
echo ERROR: Build failed. Batch stopped.
echo ********************************************************
pause
exit /b 1