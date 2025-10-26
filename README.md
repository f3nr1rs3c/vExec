# ⚙️ vExec – Remote Command Executor for vSphere VMs

**vExec**, vCenter veya ESXi üzerindeki bir sanal makine içinde, **VMware Tools** aracılığıyla uzaktan komut veya program çalıştırmaya yarayan bir Python aracıdır.

Bu sayede, hedef VM'ye SSH veya RDP bağlantısı kurmadan doğrudan **vSphere API** üzerinden program yürütülür.

---

## 🧠 Özellikler

- 🔗 vCenter veya ESXi sunucusuna güvenli bağlantı (SSL doğrulamasız mod)  
- 🧍 Belirli bir VM içinde, verilen kullanıcı bilgileriyle kimlik doğrulaması  
- ⚙️ VMware Tools aracılığıyla uzak program çalıştırma  
- ⏱️ Çalışan süreci izleme ve çıkış kodunu (exit code) raporlama  
- 🧩 Argüman desteği ve zaman aşımı (timeout) yönetimi  

---

## 🧩 Gereksinimler

Aşağıdaki Python kütüphanelerinin kurulu olması gerekir:

```bash
pip install pyvmomi
```

## ⚙️ Kullanım
```bash
python3 vexec.py --host 10.5.2.111 --user administrator@tellynet.ad --password August1990password --vm "Windows-Server01" --guest-user "Administrator" --guest-pass "WinPass123" --cmd "C:\\Windows\\System32\\cmd.exe" --args "/c echo Hello from vCollector!" --timeout 30

```
