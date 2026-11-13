# Mi 8 DarwinBoot handoff

Device: dipper, 6 GB RAM, 128 GB storage.
Observed: full green screen from the synthetic Mach-O fixture.
UEFI menu, FAT payload loading and fixture handoff verified on hardware.
Fixture uses a 16 MiB window in free static DXE heap memory.
Broad RAM access and real XNU boot remain unverified.
Diagnostic logs remain enabled.
