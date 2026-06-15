@echo off
REM ============================================================
REM  Move G:\My Drive\Aethera-CRM  →  D:\aethera-crm
REM  G: drive wins on conflicts (overwrites D: files)
REM  Google Drive will auto-download cloud-only files as needed.
REM ============================================================

echo.
echo ============================================================
echo  Moving Aethera-CRM from Google Drive to D:\aethera-crm
echo ============================================================
echo.
echo NOTE: Google Drive may download files as they are copied.
echo       This may take a few minutes depending on your connection.
echo.

SET SRC=G:\My Drive\Aethera-CRM
SET DST=D:\aethera-crm
SET LOG=D:\aethera-crm\move-log.txt

echo [1/2] Copying all files from Google Drive to D:\aethera-crm...
echo       (G: wins on conflicts - existing D: files will be overwritten)
echo.

robocopy "%SRC%" "%DST%" /E /IS /IT /IM /COPY:DAT /DCOPY:DAT /LOG:"%LOG%" /TEE /NP

if %ERRORLEVEL% GEQ 8 (
  echo.
  echo !! Some files failed to copy. Check move-log.txt for details.
  echo    Skipping deletion of source. Please review before deleting.
  goto :end
)

echo.
echo [2/2] Copy complete. Cleaning up Google Drive source folder...
echo.

REM Delete everything inside the G: folder (leave the folder itself)
rd /s /q "%SRC%"
mkdir "%SRC%"

echo.
echo ============================================================
echo  Done! All files are now in D:\aethera-crm
echo  Google Drive folder has been emptied.
echo  Log saved to: D:\aethera-crm\move-log.txt
echo ============================================================
echo.

:end
pause
