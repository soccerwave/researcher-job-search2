param(
    [Parameter(Mandatory=$true)][string]$BotToken,
    [Parameter(Mandatory=$true)][string]$WorkerUrl,
    [Parameter(Mandatory=$true)][string]$WebhookSecret
)

$body = @{
    url = ($WorkerUrl.TrimEnd('/') + '/telegram')
    secret_token = $WebhookSecret
    allowed_updates = @('message','callback_query')
    drop_pending_updates = $true
} | ConvertTo-Json -Compress

Invoke-RestMethod `
    -Uri "https://api.telegram.org/bot$BotToken/setWebhook" `
    -Method Post `
    -ContentType 'application/json' `
    -Body $body
