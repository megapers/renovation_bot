$OCI = "C:\Users\v-tmakimov\bin\oci.exe"
$COMPARTMENT_ID = "ocid1.tenancy.oc1..aaaaaaaam7oftgrfuiqitp67vl7o5d75bj2ltjpaqsvhxw7275s3jypuhbea"
$AD = "Fvxe:CA-TORONTO-1-AD-1"
$SUBNET = "ocid1.subnet.oc1.ca-toronto-1.aaaaaaaammaykroanlqrpw47yyvqih3vz445v5jpockvap5r2gszlxohlaiq"
$IMAGE = "ocid1.image.oc1.ca-toronto-1.aaaaaaaa5lalrcti6i3t46xj5afzlhqb5flu65demoskobvs4r6e3nkq37va"
$SSHKEY = "$env:USERPROFILE\.ssh\oracle_bot.pub"

Write-Host "Oracle A1.Flex Auto-Retry (4 OCPU / 24 GB)"
Write-Host "Retrying every 120s. Ctrl+C to stop."

$configFile = "$env:TEMP\oci-shape.json"
'{"ocpus":4,"memoryInGBs":24}' | Out-File -Encoding ascii $configFile

$n = 0
while ($true) {
    $n++
    $t = Get-Date -Format "HH:mm:ss"
    Write-Host "[$t] Attempt $n..."
    $r = & $OCI compute instance launch --compartment-id $COMPARTMENT_ID --availability-domain $AD --shape VM.Standard.A1.Flex --shape-config "file://$configFile" --display-name renovation-bot --image-id $IMAGE --subnet-id $SUBNET --assign-public-ip true --boot-volume-size-in-gbs 100 --ssh-authorized-keys-file $SSHKEY 2>&1 | Out-String
    if ($r -match "PROVISIONING|RUNNING") {
        Write-Host "SUCCESS!" -ForegroundColor Green
        Write-Host $r
        break
    } elseif ($r -match "capacity") {
        Write-Host "[$t] Out of capacity. Waiting 60s..." -ForegroundColor Yellow
    } else {
        Write-Host "[$t] Error (not capacity). Waiting 120s..." -ForegroundColor Red
        $r -split "`n" | Select-Object -Last 5 | ForEach-Object { Write-Host $_ }
    }
    Start-Sleep 120
}