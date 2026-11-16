# BlackBerry KEY2 Unofficial LineageOS ROM Releases

## Download/Install:
* https://github.com/Lineage-BBKey2/distribution/releases/latest

## Help/Discussion:
* Installation guide/tips: https://daphnis-past-midnight.nekoweb.org/wiki/key2.html (created/maintained by [Luna-Terra-CG](https://github.com/Luna-Terra-CG))
* Discord group for help, bug reports, feature requests, and discussion: https://discord.gg/BuJURQD6Qb
* Bug reports or feature requests can also be made here: https://github.com/Lineage-BBKey2/distribution/issues

## ROM Sources:
* Combined ROM sources for BlackBerry KEY2 and KEY2 LE are maintained [here](https://github.com/orgs/Lineage-BBKey2/repositories).
* Sources were originally forked from [krab-ubica](https://github.com/tim-ecoder/lineageos_blackberry_athena) and [FumoEnterprises](https://github.com/FumoEnterprises) - this foundational work is greatly appreciated!

## ADB-only configurations:

### Enable/disable MGLRU:
- MGLRU (Multi-Generational Least Recently Used) is a newer memory management algorithm (backported to kernel 4.19) intended to improve memory reclaiming decisions when available memory is low. 
- MGLRU is off by default on this ROM because its overall benefit and impact on performance and battery life has not been adequately assessed. It has also not been shown to break anything, so users who wish to experiment with it can enable or re-disable it as shown below.
- Enable MGLRU:
  ```
  adb root
  adb wait-for-device
  adb shell setprop persist.vendor.key2.mglru.enabled 1
  adb reboot
  ```
  (after reboot confirm change with:)
  ```
  adb root
  adb wait-for-device
  adb shell getprop persist.vendor.key2.mglru.enabled
  adb shell cat /sys/kernel/mm/lru_gen/enabled
  ```
    - The last two lines should produce `1` and `0x0001`.

- Disable MGLRU:
  ```
  adb root
  adb wait-for-device
  adb shell setprop persist.vendor.key2.mglru.enabled 0
  adb reboot
  ```
  (after reboot confirm change with:)
  ```
  adb root
  adb wait-for-device
  adb shell getprop persist.vendor.key2.mglru.enabled
  adb shell cat /sys/kernel/mm/lru_gen/enabled
  ```
    - The last two lines should produce `0` and `0x0000`

### Check/Switch ZRAM Compression Algorithm:
- LZ4 is the recommended compression algorithm. ZSTD gives higher compression ratios, but at the cost of higher CPU usage which the KEY2's SDM660 processor may not handle well.
- Check current compression algorithm:
  ```
  adb root
  adb wait-for-device
  adb shell cat /sys/block/zram0/comp_algorithm
  ```
- Switch to LZ4 compression (substitute `zstd` or `lzo` if those are desired):
  ```
  adb root
  adb wait-for-device
  adb shell setprop persist.vendor.key2.zram.compressor lz4
  adb reboot
  ```
  (after reboot confirm change with:)
  ```
  adb root
  adb shell cat /sys/block/zram0/comp_algorithm
  ```

## Download history

### Last 30 days

![Cumulative downloads for the newest three ROM releases over the last 30 days](stats/downloads-30days-light.svg#gh-light-mode-only)
![Cumulative downloads for the newest three ROM releases over the last 30 days](stats/downloads-30days-dark.svg#gh-dark-mode-only)

### Full history

![Cumulative ROM downloads over the complete history](stats/downloads-total-light.svg#gh-light-mode-only)
![Cumulative ROM downloads over the complete history](stats/downloads-total-dark.svg#gh-dark-mode-only)

### Downloads per day

![Combined downloads per day over the complete history](stats/downloads-daily-light.svg#gh-light-mode-only)
![Combined downloads per day over the complete history](stats/downloads-daily-dark.svg#gh-dark-mode-only)
