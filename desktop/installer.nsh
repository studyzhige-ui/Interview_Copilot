; Electron creates the per-user URI association on first launch. NSIS does not
; register/unregister build.protocols. Remove only this installation's exact
; command, preserving an association subsequently assigned to another app.
!macro customUnInstall
  Push $R0
  ReadRegStr $R0 HKCU "Software\Classes\interview-copilot\shell\open\command" ""
  ${If} $R0 == '"$INSTDIR\${APP_EXECUTABLE_FILENAME}" "%1"'
    DeleteRegKey HKCU "Software\Classes\interview-copilot"
  ${EndIf}
  Pop $R0
!macroend
