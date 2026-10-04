@echo off
echo 🛡️ AEGIS CLOUD AUTOMATOR
echo ━━━━━━━━━━━━━━━━━━━━━━
git add .
set /p msg="Enter commit message (or press enter for 'auto-update'): "
if "%msg%"=="" set msg="auto-update"
git commit -m "%msg%"
git push origin main
echo ━━━━━━━━━━━━━━━━━━━━━━
echo ✅ Update pushed. Railway daemon and Streamlit Cloud are deploying.
pause