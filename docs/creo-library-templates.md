# Creo templates and libraries with CreoPDM

Store shared Creo start parts, assemblies, formats, symbols, and libraries in a CreoPDM project on the Linux host. Windows Creo PCs then open those files over SMB using UNC paths in `config.pro`.

This guide assumes:

- CreoPDM runs on a Linux host (hostname example: `creopdm`)
- Vaults live under `~/.local/share/CreoPDM/vaults`
- Creo runs on Windows on the same LAN

---

## 1. Create a Library project in CreoPDM

1. Open CreoPDM in the browser and choose **New**.
2. **Name:** `Library` (display name in CreoPDM).
3. Uncheck **Use hash**.
4. **Vault/Workspace name:** `library` (lowercase; this becomes the folder under `vaults/`).
5. Create the project.

On the Linux host the vault is:

```text
~/.local/share/CreoPDM/vaults/library
```

Add your resources into that vault through CreoPDM (Add files / folder), for example:

```text
library/
  model-templates/
    start_part.prt
    start_assy.asm
  formats/
  symbols/
  …
```

Check the files in so the vault holds the shared revisions. Creo on Windows will read them through the SMB share below (read-only is typical for a central library).

---

## 2. Share the vaults folder with Samba

An SMB share lets Creo on Windows use UNC paths such as `\\creopdm\creopdm-vaults\library\…`.

### Install Samba

```bash
sudo apt update
sudo apt install samba
```

Confirm the vault path exists (after you created the Library project):

```bash
ls ~/.local/share/CreoPDM/vaults/library
```

### Configure the share

Open the Samba configuration:

```bash
sudo nano /etc/samba/smb.conf
```

Under the existing `[global]` section, add:

```ini
map to guest = Bad User
```

At the end of the file, add a share that points at the CreoPDM vaults directory. Replace `exampleuser` with the Linux account that owns `~/.local/share/CreoPDM`:

```ini
[creopdm-vaults]
    path = /home/exampleuser/.local/share/CreoPDM/vaults
    browseable = yes
    guest ok = yes
    guest only = yes
    force user = exampleuser
    read only = yes
```

Sharing `vaults` (not only `library`) keeps UNC paths short and lets you add more shared projects later under the same share.

Check the configuration and start Samba:

```bash
testparm
sudo systemctl enable --now smbd
sudo systemctl restart smbd
```

### Allow SMB through the firewall

Replace `192.168.1.0/24` with your LAN:

```bash
sudo ufw allow from 192.168.1.0/24 to any port 445 proto tcp
```

### Open the share from Windows

In File Explorer:

```text
\\creopdm\creopdm-vaults
```

You should see a `library` folder (and any other project vault folders). The `creopdm` hostname must resolve on your network (DNS, mDNS, or a `hosts` entry).

If Windows blocks unauthenticated guest access, run PowerShell **as Administrator**:

```powershell
Set-SmbClientConfiguration -EnableInsecureGuestLogons $true -Force
```

Guest access may also be blocked when Windows requires SMB signing. The share is read-only, but anyone who can reach it can read its files—limit firewall access to your trusted network.

---

## 3. Point Creo at the Library vault (`config.pro`)

In Creo Parametric, set search / template options to the UNC paths. Adjust subfolders and filenames to match what you stored in the Library project.

Example (`config.pro`):

```text
pro_library_dir \\creopdm\creopdm-vaults\library
template_solidpart \\creopdm\creopdm-vaults\library\model-templates\start_part.prt
template_designasm \\creopdm\creopdm-vaults\library\model-templates\start_assy.asm
```

Notes:

| Option | Role |
|--------|------|
| `pro_library_dir` | Root for library browsing / related library paths |
| `template_solidpart` | Default start part when creating a new solid |
| `template_designasm` | Default start assembly when creating a new assembly |

You can add further options the same way (formats, drawings, sheetmetal start models, and so on), always under `\\creopdm\creopdm-vaults\library\…`.

After changing `config.pro`, restart Creo (or reload configuration) so the new paths apply. Confirm File Explorer can open the UNC path before debugging Creo if a template fails to load.

---

## 4. Workflow summary

1. Maintain templates and libraries in the CreoPDM **Library** project (`vault` = `library`).
2. Check in updates on the Linux CreoPDM host as usual.
3. Windows Creo reads the same files over `\\creopdm\creopdm-vaults\library` (no separate copy required).
4. Keep the Samba share **read-only** so day-to-day Creo use does not write around CreoPDM; change library content through CreoPDM check-in.

If you use a different hostname or Linux username, replace `creopdm` and `exampleuser` everywhere above. If your vaults directory was customized in CreoPDM Settings, point Samba `path=` at that folder instead of `~/.local/share/CreoPDM/vaults`.
