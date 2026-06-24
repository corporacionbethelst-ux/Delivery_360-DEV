# 🔀 Guía Completa de Git: Control de Versiones

> Esta guía está pensada para **PowerShell en Windows**, aunque la mayoría de comandos son universales. Cubre desde tu primer `git init` hasta estrategias avanzadas de versionado y flujos de trabajo en equipo.

---

## 📋 Tabla de Contenidos

1. [Configuración Inicial](#-configuración-inicial)
2. [Nivel Básico](#-nivel-básico-el-día-a-día)
3. [Nivel Intermedio](#-nivel-intermedio-ramas-y-remotos)
4. [Nivel Avanzado](#-nivel-avanzado-reescritura-y-depuración)
5. [Etiquetas y Versiones Semánticas](#-etiquetas-y-versionado-semántico)
6. [Flujos de Trabajo](#-flujos-de-trabajo-workflows)
7. [Buenas Prácticas](#-buenas-prácticas)
8. [Trucos para PowerShell](#-trucos-específicos-para-powershell)

---

## ⚙️ Configuración Inicial

Lo primero que debes hacer **una sola vez** al instalar Git.

### 1. Instalar Git
Descárgalo desde [git-scm.com](https://git-scm.com/) y durante la instalación:
- Selecciona **"Git from the command line and also from 3rd-party software"**
- Selecciona **"Use PowerShell as Git's default editor"** (opcional, pero recomendado)

### 2. Configurar tu identidad
```powershell
# Tu nombre (aparecerá en cada commit)
git config --global user.name "Tu Nombre Completo"

# Tu email (debe coincidir con el de GitHub/GitLab)
git config --global user.email "tu.email@ejemplo.com"
```

### 3. Configurar el editor por defecto
```powershell
# Para usar VS Code como editor de commits y merges
git config --global core.editor "code --wait"
```

### 4. Ver tu configuración actual
```powershell
git config --global --list
```

### 5. Generar clave SSH (para GitHub/GitLab sin contraseña)
```powershell
ssh-keygen -t ed25519 -C "tu.email@ejemplo.com"
# Acepta la ruta por defecto (Enter), pon una passphrase si quieres
cat ~/.ssh/id_ed25519.pub | clip   # Copia la clave al portapapeles
```
> Luego pégala en: **GitHub → Settings → SSH and GPG keys → New SSH key**

---

## 🟢 Nivel Básico: El día a día

### 1. Inicializar un repositorio
```powershell
# Crear un repo nuevo en la carpeta actual
git init

# O clonar un repo existente
git clone https://github.com/usuario/proyecto.git
git clone git@github.com:usuario/proyecto.git  # Con SSH
```

### 2. El ciclo de vida de un archivo
Git maneja **3 áreas** que debes entender:

```
Working Directory  →  Staging Area  →  Repository
  (tu carpeta)        (git add)        (git commit)
```

```powershell
# Ver qué archivos cambiaron
git status

# Agregar un archivo al staging
git add archivo.txt

# Agregar TODOS los archivos modificados
git add .

# Agregar solo archivos de una carpeta
git add src/

# Hacer un commit (guardar la versión)
git commit -m "feat: agregar módulo de autenticación"

# Agregar y hacer commit en un solo paso (solo archivos ya rastreados)
git commit -am "fix: corregir bug en el login"
```

### 3. Ver el historial
```powershell
# Historial completo
git log

# Historial resumido (una línea por commit)
git log --oneline

# Historial con gráfico de ramas visual
git log --oneline --graph --all --decorate

# Historial de un archivo específico
git log --follow -- ruta/al/archivo.txt

# Ver los últimos 5 commits
git log -5 --oneline
```

### 4. Ver cambios (diff)
```powershell
# Cambios no guardados (working directory vs staging)
git diff

# Cambios en staging (staging vs último commit)
git diff --staged

# Cambios entre dos commits
git diff abc1234 def5678

# Cambios entre dos ramas
git diff main..feature/login
```

### 5. Deshacer cosas (con cuidado)
```powershell
# Descartar cambios en un archivo (¡irreversible!)
git checkout -- archivo.txt
git restore archivo.txt           # Forma moderna

# Quitar un archivo del staging (pero mantener los cambios)
git restore --staged archivo.txt
git reset HEAD archivo.txt        # Forma clásica

# Corregir el mensaje del ÚLTIMO commit
git commit --amend -m "mensaje corregido"

# Agregar archivos olvidados al último commit
git add archivo_olvidado.txt
git commit --amend --no-edit
```

### 6. Ignorar archivos (.gitignore)
Crea un archivo `.gitignore` en la raíz del proyecto:

```gitignore
# Dependencias
node_modules/
vendor/
__pycache__/

# Archivos de entorno (¡NUNCA subas secretos!)
.env
.env.local
.env.production

# Archivos compilados
dist/
build/
*.exe
*.dll

# Configuración de IDE
.vscode/
.idea/
*.swp

# Logs
*.log

# Archivos de sistema operativo
Thumbs.db
.DS_Store
```

> **Regla de oro:** Si ya commiteaste un archivo y luego lo agregas al `.gitignore`, Git lo seguirá rastreando. Debes eliminarlo del índice:
> ```powershell
> git rm --cached archivo_secreto.txt
> git rm -r --cached node_modules/
> git commit -m "chore: eliminar archivos que no deben estar en el repo"
> ```

---

## 🟡 Nivel Intermedio: Ramas y Remotos

### 1. Trabajar con ramas (Branches)
Las ramas son **la razón de existir de Git**. Te permiten trabajar en funcionalidades sin tocar el código estable.

```powershell
# Ver todas las ramas
git branch

# Crear una nueva rama
git branch feature/login

# Cambiarse a una rama
git switch feature/login       # Forma moderna
git checkout feature/login     # Forma clásica

# Crear Y cambiarse en un solo paso
git switch -c feature/login
git checkout -b feature/login

# Eliminar una rama (ya mergeada)
git branch -d feature/login

# Eliminar una rama forzosamente (no mergeada, ¡cuidado!)
git branch -D feature/login

# Renombrar la rama actual
git branch -m nuevo-nombre
```

### 2. Fusionar ramas (Merge)
```powershell
# Asegúrate de estar en la rama destino
git switch main

# Fusionar feature/login dentro de main
git merge feature/login

# Si hay conflictos, Git te pedirá resolverlos:
# 1. Abre los archivos en conflicto
# 2. Busca los marcadores:
#    <<<<<<< HEAD
#    tu código en main
#    =======
#    código de feature/login
#    >>>>>>> feature/login
# 3. Elige qué código conservar
# 4. Marca como resuelto:
git add archivo_en_conflicto.txt
git commit -m "merge: resolver conflictos en login"

# Abortar un merge si te arrepientes
git merge --abort
```

### 3. Trabajar con repositorios remotos
```powershell
# Ver los remotos configurados
git remote -v

# Agregar un remoto
git remote add origin git@github.com:usuario/proyecto.git

# Subir cambios al remoto (primera vez, vincula la rama)
git push -u origin main

# Subir cambios (veces siguientes)
git push

# Descargar cambios del remoto (sin fusionar, solo inspeccionar)
git fetch origin

# Descargar Y fusionar (fetch + merge)
git pull origin main

# Si tu rama local y la remota divergieron:
git pull --rebase origin main
```

### 4. Stash (Guardar cambios temporales)
Cuando estás a medias de algo y necesitas cambiar de rama urgentemente.

```powershell
# Guardar cambios temporales
git stash
git stash save "WIP: login a medias"   # Con descripción

# Ver lo que guardaste
git stash list

# Recuperar el último stash (lo aplica y lo borra de la lista)
git stash pop

# Recuperar sin borrar de la lista
git stash apply stash@{0}

# Eliminar un stash específico
git stash drop stash@{0}

# Limpiar todos los stashes
git stash clear
```

---

## 🔴 Nivel Avanzado: Reescritura y Depuración

### 1. Rebase (Historial lineal)
A diferencia de merge, rebase reescribe el historial para que parezca que tus cambios se hicieron sobre la última versión.

```powershell
# Rebasear tu rama sobre main
git switch feature/login
git rebase main

# Si hay conflictos durante el rebase:
# 1. Resuelve los conflictos en el archivo
git add archivo.txt
git rebase --continue

# Para abortar
git rebase --abort

# ⚠️ REGLA DE ORO DEL REBASE:
# NUNCA hagas rebase de ramas que ya están subidas al remoto
# y que otros usan. Solo rebasea tu trabajo LOCAL.
```

### 2. Rebase interactivo (Reescribir historia)
Para limpiar commits antes de hacer push.

```powershell
# Reescribir los últimos 3 commits
git rebase -i HEAD~3
```

Se abrirá un editor con algo como:
```
pick abc1234 feat: agregar login
pick def5678 fix: typo en login
pick ghi9012 fix: otro typo

# Comandos disponibles:
# pick   = usar el commit tal cual
# reword = usar el commit pero cambiar el mensaje
# edit   = pausar para modificar el commit
# squash = fusionar con el commit anterior
# fixup  = como squash pero descarta el mensaje
# drop   = eliminar el commit
```

Ejemplo para fusionar los 3 commits en uno:
```
pick abc1234 feat: agregar login
squash def5678 fix: typo en login
squash ghi9012 fix: otro typo
```

### 3. Cherry-pick (Copiar un commit específico)
```powershell
# Aplicar un commit específico de otra rama
git cherry-pick abc1234

# Aplicar sin hacer commit automático (para revisar antes)
git cherry-pick --no-commit abc1234

# Aplicar un rango de commits
git cherry-pick abc1234..def5678
```

### 4. Bisect (Encontrar el commit que rompió algo)
Búsqueda binaria automática entre commits.

```powershell
# Iniciar bisect
git bisect start

# Marcar el commit actual como malo
git bisect bad

# Marcar un commit antiguo como bueno (ej: versión 1.0)
git bisect good v1.0

# Git te llevará a un commit intermedio.
# Prueba si funciona y marca:
git bisect good   # si funciona
git bisect bad    # si falla

# Repite hasta que Git encuentre el commit culpable
# Para terminar:
git bisect reset
```

### 5. Reflog (Tu red de seguridad)
Git registra TODO lo que haces, incluso lo que borras.

```powershell
# Ver el registro de movimientos del HEAD
git reflog

# Ejemplo de salida:
# abc1234 HEAD@{0}: commit: fix login
# def5678 HEAD@{1}: checkout: moving from main to feature
# ghi9012 HEAD@{2}: reset: moving to HEAD~3

# Recuperar un commit "perdido"
git checkout abc1234
# o
git reset --hard abc1234   # ⚠️ Irreversible para el working dir
```

### 6. Reset (Mover el puntero HEAD)
```powershell
# ⚠️ soft: Mueve HEAD, mantiene cambios en staging
git reset --soft HEAD~1

# ⚠️ mixed (default): Mueve HEAD, mantiene cambios en working dir
git reset HEAD~1

# 🚨 hard: Mueve HEAD y ELIMINA todos los cambios (¡peligroso!)
git reset --hard HEAD~1

# Deshacer el último push (forzar en remoto)
git reset --hard HEAD~1
git push --force-with-lease origin main
# --force-with-lease es más seguro que --force (verifica que nadie
# haya subido cambios nuevos que perderías)
```

---

## 🏷️ Etiquetas y Versionado Semántico

### 1. Crear etiquetas (Tags)
```powershell
# Etiqueta ligera (solo un puntero)
git tag v1.0.0

# Etiqueta anotada (recomendada, incluye autor, fecha, mensaje)
git tag -a v1.0.0 -m "Lanzamiento versión 1.0.0"

# Etiquetar un commit específico del pasado
git tag -a v0.9.0 abc1234 -m "Versión beta"

# Ver todas las etiquetas
git tag

# Buscar etiquetas con patrón
git tag -l "v1.*"

# Subir etiquetas al remoto (no se suben automáticamente)
git push origin v1.0.0           # Una específica
git push origin --tags           # Todas
```

### 2. Versionado Semántico (SemVer)

Convención estándar para nombrar versiones: **MAJOR.MINOR.PATCH**

```
v2.5.3
│ │ └── PATCH: Bug fixes (2.5.2 → 2.5.3)
│ └──── MINOR: Nuevas features compatibles (2.4.0 → 2.5.0)
└────── MAJOR: Cambios que rompen compatibilidad (1.5.3 → 2.0.0)
```

### 3. Generar changelog desde tags
```powershell
# Ver cambios entre dos versiones
git log v1.0.0..v2.0.0 --oneline

# Ver qué archivos cambiaron entre versiones
git diff v1.0.0..v2.0.0 --stat
```

### 4. Workflow recomendado de releases
```powershell
# 1. Asegurarte de que main está actualizado
git switch main
git pull origin main

# 2. Crear tag
git tag -a v1.2.0 -m "Release 1.2.0: nuevo módulo de pagos"

# 3. Subir tag
git push origin v1.2.0

# 4. En GitHub/GitLab, crear Release desde el tag
#    (puedes adjuntar binarios, notas de release, etc.)
```

---

## 🔀 Flujos de Trabajo (Workflows)

### 1. Git Flow (Proyectos con releases formales)

```
main ──────────●──────────●──────── (producción estable)
                \        /
release/1.0 ─────●──●──●           (preparación de release)
                  \
develop ──●──●──●──●──●──●──●──●── (desarrollo continuo)
           \     /      \     /
feature/   ──●──        ──●──      (funcionalidades)
```

```powershell
# Ramas principales (siempre existen)
main       # Solo código en producción
develop    # Integración de features

# Ramas temporales
feature/nombre    # Nacen de develop, vuelven a develop
release/x.x       # Nacen de develop, van a main Y develop
hotfix/nombre     # Nacen de main, van a main Y develop
```

**Ejemplo práctico - Nueva feature:**
```powershell
# 1. Crear feature desde develop
git switch develop
git pull origin develop
git switch -c feature/carrito-compras

# 2. Trabajar y hacer commits
git add .
git commit -m "feat: agregar componente del carrito"

# 3. Subir la rama
git push -u origin feature/carrito-compras

# 4. Crear Pull Request en GitHub/GitLab
# 5. Tras aprobación, se mergea a develop
```

**Ejemplo práctico - Hotfix urgente:**
```powershell
# 1. Crear hotfix desde main
git switch main
git pull origin main
git switch -c hotfix/critical-bug

# 2. Arreglar y commitear
git commit -am "fix: parche crítico en pagos"

# 3. Merge a main Y a develop
git switch main
git merge hotfix/critical-bug
git tag -a v1.0.1 -m "Hotfix: critical bug"
git push origin main --tags

git switch develop
git merge hotfix/critical-bug
git push origin develop

# 4. Eliminar rama temporal
git branch -d hotfix/critical-bug
```

### 2. Trunk-Based Development (Equipos ágiles/CI-CD)

```
main ──●──●──●──●──●──●──●──●── (siempre deployable)
        \  /    \  /    \  /
         ●       ●       ●        (branches cortas, <1 día)
```

```powershell
# Las ramas viven horas, no semanas
git switch -c fix/typo
git commit -am "fix: typo en header"
git push -u origin fix/typo
# PR rápido → merge → delete branch
```

---

## ✅ Buenas Prácticas

### 1. Convención de mensajes de commit (Conventional Commits)

```
<tipo>(<alcance>): <descripción corta>

<cuerpo opcional con más detalles>

<footer opcional: BREAKING CHANGE, refs, etc.>
```

**Tipos estándar:**
| Tipo       | Uso                                           |
|------------|-----------------------------------------------|
| `feat`     | Nueva funcionalidad                           |
| `fix`      | Corrección de bug                             |
| `docs`     | Cambios en documentación                      |
| `style`    | Formato (espacios, comas, sin cambio de lógica)|
| `refactor` | Reestructurar código sin cambiar comportamiento|
| `test`     | Agregar o corregir tests                      |
| `chore`    | Tareas de mantenimiento (deps, config)        |
| `ci`       | Cambios en CI/CD                              |
| `perf`     | Mejoras de rendimiento                        |

**Ejemplos buenos:**
```
feat(auth): agregar login con Google OAuth
fix(api): corregir paginación en endpoint de usuarios
docs(readme): actualizar instrucciones de instalación
refactor(cart): extraer lógica de cálculo de impuestos
chore(deps): actualizar express a v5.0.0
```

**Ejemplos malos ❌:**
```
cambios
fix
actualizar cosas
WIP
arreglar bug
```

### 2. Reglas generales
- ✅ Haz commits **pequeños y frecuentes** (un cambio lógico por commit)
- ✅ Escribe mensajes en **imperativo**: "agregar" no "agregado" ni "agregué"
- ✅ **Nunca** subas `.env`, claves API, ni contraseñas
- ✅ Usa **Pull Requests**, no pushes directos a `main`
- ✅ Configura **branch protection rules** en GitHub/GitLab para `main`
- ❌ Nunca hagas `git push --force` a ramas compartidas
- ❌ No hagas commits gigantes con 50 archivos modificados

---

## 💻 Trucos Específicos para PowerShell

### 1. Alias útiles en PowerShell
Agrega esto a tu perfil (`notepad $PROFILE`):

```powershell
# PowerShell Profile - Git Aliases
function gs { git status }
function ga { git add . }
function gc { param([string]$msg) git commit -m $msg }
function gp { git push }
function gl { git pull }
function gd { git diff }
function glog { git log --oneline --graph --all --decorate }
function gsw { param([string]$branch) git switch $branch }
function gcb { param([string]$branch) git switch -c $branch }

# Alias para mensajes largos (abre editor)
function gca { git commit }
```

### 2. Autocompletado de Git en PowerShell
```powershell
# Instalar módulo de autocompletado
Install-Module posh-git -Scope CurrentUser

# Agregar al perfil
Import-Module posh-git

# Esto te dará:
# - Autocompletado de comandos git con Tab
# - Estado del repo en el prompt (rama, archivos modificados, etc.)
```

### 3. Problemas comunes en PowerShell

**Problema:** `git commit` no abre el editor.
```powershell
# Solución: Configurar VS Code como editor
git config --global core.editor "code --wait"
```

**Problema:** Caracteres especiales (tildes, ñ) se ven mal.
```powershell
# Solución: Forzar UTF-8
git config --global core.quotepath false
git config --global i18n.commitEncoding utf-8
git config --global i18n.logOutputEncoding utf-8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

**Problema:** `fatal: LF will be replaced by CRLF`
```powershell
# Solución: Normalizar saltos de línea
git config --global core.autocrlf true   # Windows
# En Linux/Mac sería: git config --global core.autocrlf input
```

### 4. Script PowerShell para ver estado rápido del proyecto
```powershell
# Guardar como git-summary.ps1
function Get-GitSummary {
    Write-Host "📂 Repo: " -NoNewline -ForegroundColor Cyan
    Write-Host (Split-Path -Leaf (git rev-parse --show-toplevel))

    Write-Host "🌿 Rama: " -NoNewline -ForegroundColor Green
    Write-Host (git branch --show-current)

    Write-Host "📝 Cambios: " -NoNewline -ForegroundColor Yellow
    $changes = (git status --porcelain | Measure-Object).Count
    Write-Host "$changes archivo(s)"

    Write-Host "📦 Último commit: " -NoNewline -ForegroundColor Magenta
    Write-Host (git log -1 --format="%h %s")

    Write-Host "🏷️  Último tag: " -NoNewline -ForegroundColor DarkYellow
    Write-Host (git describe --tags --abbrev=0 2>$null ?? "Sin tags")
}
```

---

## 🗺️ Mapa Mental: ¿Qué comando uso?

```
¿Qué quiero hacer?
│
├─ Guardar mi trabajo
│   ├─ git add .
│   └─ git commit -m "mensaje"
│
├─ Subir al remoto
│   └─ git push
│
├─ Traer cambios del equipo
│   ├─ git pull (fetch + merge)
│   └─ git fetch + git rebase (más limpio)
│
├─ Trabajar en paralelo
│   ├─ git switch -c feature/x
│   └─ git merge / git rebase
│
├─ Deshacer algo
│   ├─ git restore (archivos)
│   ├─ git commit --amend (último commit)
│   ├─ git reset --soft/mixed/hard (mover HEAD)
│   └─ git reflog (recuperar lo "perdido")
│
├─ Guardar cambios a medias
│   └─ git stash → git stash pop
│
├─ Marcar una versión
│   └─ git tag -a v1.0.0 -m "Release"
│
└─ Encontrar un bug
    └─ git bisect start/bad/good
```

---

> **💡 Consejo final:** Si alguna vez sientes que "rompiste todo", respira. Git casi nunca pierde datos. Usa `git reflog` para ver todos los movimientos que has hecho y `git reset --hard <hash>` para volver a cualquier punto anterior. La única forma real de perder datos es con `git push --force` o borrando ramas sin merge.