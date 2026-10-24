# Every function below breaks one rule and the script has no header block.
function DoThing { 'x' }
function Fetch-Data { 'y' }
function Get-Item_Data { 'z' }
try { DoThing } catch { }
try { Fetch-Data } catch [System.IO.IOException] {
    # a comment is not a statement
}
