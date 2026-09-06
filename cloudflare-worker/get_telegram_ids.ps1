param(
    [Parameter(Mandatory=$true)][string]$BotToken
)

$uri = "https://api.telegram.org/bot$BotToken/getUpdates"
$result = Invoke-RestMethod -Uri $uri -Method Get
$result.result | ForEach-Object {
    if ($_.message) {
        [PSCustomObject]@{
            UserId   = $_.message.from.id
            Username = $_.message.from.username
            FirstName = $_.message.from.first_name
            ChatId   = $_.message.chat.id
            ChatType = $_.message.chat.type
            Text     = $_.message.text
        }
    }
} | Format-Table -AutoSize
