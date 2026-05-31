@echo off
cd /d "%~dp0"
py -3.13 -m streamlit run app.py --server.address=0.0.0.0 --server.port=8501 --server.headless=true
