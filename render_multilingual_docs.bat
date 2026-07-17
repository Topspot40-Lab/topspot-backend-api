@echo off
title TopSpot Studio - ES/PT-BR Documentary Render
cd /d C:\Users\Owner\pp\topspot-backend-api

echo ================================================================
echo TopSpot Studio - Multilingual Documentary Render
echo ================================================================
echo.

REM ------------------------------------------------------------
REM Ed Sullivan
REM ------------------------------------------------------------
echo === Ed Sullivan (ES) ===
.venv\Scripts\python -m dotenv run -- .venv\Scripts\python -m backend.studio.render.build_story_video --slug ed_sullivan --language es

echo === Ed Sullivan (PT-BR) ===
.venv\Scripts\python -m dotenv run -- .venv\Scripts\python -m backend.studio.render.build_story_video --slug ed_sullivan --language pt-BR

REM ------------------------------------------------------------
REM Dick Clark
REM ------------------------------------------------------------
echo === Dick Clark (ES) ===
.venv\Scripts\python -m dotenv run -- .venv\Scripts\python -m backend.studio.render.build_story_video --slug dick_clark --language es

echo === Dick Clark (PT-BR) ===
.venv\Scripts\python -m dotenv run -- .venv\Scripts\python -m backend.studio.render.build_story_video --slug dick_clark --language pt-BR

REM ------------------------------------------------------------
REM Johnny Cash
REM ------------------------------------------------------------
echo === Johnny Cash (ES) ===
.venv\Scripts\python -m dotenv run -- .venv\Scripts\python -m backend.studio.render.build_story_video --slug johnny_cash --language es

echo === Johnny Cash (PT-BR) ===
.venv\Scripts\python -m dotenv run -- .venv\Scripts\python -m backend.studio.render.build_story_video --slug johnny_cash --language pt-BR

REM ------------------------------------------------------------
REM Casey Kasem
REM ------------------------------------------------------------
echo === Casey Kasem (ES) ===
.venv\Scripts\python -m dotenv run -- .venv\Scripts\python -m backend.studio.render.build_story_video --slug casey_kasem --language es

echo === Casey Kasem (PT-BR) ===
.venv\Scripts\python -m dotenv run -- .venv\Scripts\python -m backend.studio.render.build_story_video --slug casey_kasem --language pt-BR

REM ------------------------------------------------------------
REM Juan Gabriel
REM ------------------------------------------------------------
echo === Juan Gabriel (ES) ===
.venv\Scripts\python -m dotenv run -- .venv\Scripts\python -m backend.studio.render.build_story_video --slug juan_gabriel --language es

echo === Juan Gabriel (PT-BR) ===
.venv\Scripts\python -m dotenv run -- .venv\Scripts\python -m backend.studio.render.build_story_video --slug juan_gabriel --language pt-BR

REM ------------------------------------------------------------
REM Luis Miguel
REM ------------------------------------------------------------
echo === Luis Miguel (ES) ===
.venv\Scripts\python -m dotenv run -- .venv\Scripts\python -m backend.studio.render.build_story_video --slug luis_miguel --language es

echo === Luis Miguel (PT-BR) ===
.venv\Scripts\python -m dotenv run -- .venv\Scripts\python -m backend.studio.render.build_story_video --slug luis_miguel --language pt-BR

echo.
echo ================================================================
echo All multilingual renders complete.
echo ================================================================
pause