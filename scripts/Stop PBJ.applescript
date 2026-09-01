on run
    set scriptFile to POSIX path of (path to me)
    set scriptsFolder to do shell script "/usr/bin/dirname " & quoted form of scriptFile
    set projectFolder to do shell script "/usr/bin/dirname " & quoted form of scriptsFolder
    set stopScript to projectFolder & "/stop_pbj.command"
    try
        set resultMessage to do shell script "/bin/zsh " & quoted form of stopScript
        display dialog resultMessage with title "PB&J" buttons {"OK"} default button "OK" with icon note
    on error errorMessage
        display dialog "PBJ could not be stopped: " & errorMessage with title "PB&J" buttons {"OK"} default button "OK" with icon stop
    end try
end run
