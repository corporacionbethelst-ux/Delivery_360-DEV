
Está estructurada desde lo más básico hasta comandos avanzados, incluyendo trucos específicos para PowerShell (como el manejo de variables de entorno, que es diferente a Linux/Mac).

***

# 🐳 Guía de Docker Compose para PowerShell

> **Nota previa:** En las versiones modernas de Docker Desktop, el comando nativo es `docker compose` (sin guion). Sin embargo, `docker-compose` (con guion) sigue funcionando como un alias. En esta guía usaremos `docker-compose` como lo solicitaste.

## 📋 Prerrequisitos
1. Tener **Docker Desktop** instalado y corriendo.
2. Abrir **PowerShell** y navegar a la carpeta donde está tu archivo `docker-compose.yml`:
   ```powershell
   cd C:\ruta\a\tu\proyecto
   ```

---

## 🟢 Nivel 1: Comandos Básicos (El día a día)

Estos son los comandos que usarás el 90% del tiempo para levantar, bajar y revisar tus contenedores.

### 1. Levantar y compilar (Tu ejemplo)
Construye las imágenes (si hay cambios en el Dockerfile) y levanta los contenedores en segundo plano.
```powershell
docker-compose up -d --build
```
* `-d` (detach): Corre los contenedores en segundo plano.
* `--build`: Fuerza la reconstrucción de las imágenes antes de levantarlos.

### 2. Levantar sin compilar
Si no has cambiado el código o el Dockerfile, usa esto para que inicie más rápido.
```powershell
docker-compose up -d
```

### 3. Ver el estado de los contenedores
Muestra qué contenedores están corriendo, sus puertos y estado.
```powershell
docker-compose ps
```

### 4. Ver los logs (Registros)
Para ver qué está pasando dentro de tus aplicaciones.
```powershell
# Ver logs de todos los servicios
docker-compose logs

# Ver logs en tiempo real (follow)
docker-compose logs -f

# Ver logs de un servicio específico
docker-compose logs -f nombre_del_servicio
```

### 5. Detener y eliminar todo
Apaga los contenedores y elimina las redes creadas por compose.
```powershell
docker-compose down
```

---

## 🟡 Nivel 2: Comandos Intermedios (Control específico)

Cuando necesitas manipular un servicio en particular o reiniciar cosas sin bajar todo.

### 1. Reiniciar un servicio específico
```powershell
docker-compose restart nombre_del_servicio
```

### 2. Detener sin eliminar (Mantiene los volúmenes y redes)
```powershell
docker-compose stop
```
*(Para volver a iniciarlos después, usa `docker-compose start`)*.

### 3. Entrar a la terminal de un contenedor (Exec)
Muy útil para depurar, revisar archivos internos o conectar a bases de datos.
```powershell
# Entrar con sh (funciona en la mayoría de imágenes Linux)
docker-compose exec nombre_del_servicio sh

# Entrar con bash (si la imagen lo tiene instalado)
docker-compose exec nombre_del_servicio bash
```
*Para salir de la terminal del contenedor, escribe `exit`.*

### 4. Reconstruir solo un servicio
Si solo cambiaste el código de un microservicio y no quieres reconstruir todo.
```powershell
docker-compose up -d --build --no-deps nombre_del_servicio
```

---

## 🔴 Nivel 3: Comandos Avanzados y Limpieza

Para cuando las cosas se rompen, necesitas depurar a fondo o limpiar el sistema.

### 1. Forzar recreación de contenedores
Úsalo si cambiaste variables de entorno en el `.env` o en el `yml` y los contenedores no las están tomando.
```powershell
docker-compose up -d --force-recreate
```

### 2. Eliminar contenedores huérfanos
Si quitaste un servicio del `docker-compose.yml` pero su contenedor sigue corriendo "fantasma".
```powershell
docker-compose down --remove-orphans
```

### 3. Usar múltiples archivos de compose (Overriding)
Ideal para separar configuración de desarrollo y producción.
```powershell
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### 4. Limpieza nuclear (Borrar todo lo no usado)
Si tu disco se está llenando de imágenes y volúmenes viejos. **¡Cuidado! Esto borra todo lo que no esté en uso.**
```powershell
# Borrar contenedores, redes y imágenes detenidas
docker system prune -a

# Borrar TODO (incluyendo volúmenes con datos de bases de datos)
docker system prune -a --volumes
```

---

## 💡 Trucos Específicos para PowerShell

PowerShell maneja las cosas de forma distinta a Bash (Linux/Mac). Aquí tienes las soluciones a los problemas más comunes:

### 1. Pasar Variables de Entorno en línea
En Linux harías `MI_VAR=valor docker-compose up`. **En PowerShell esto da error.**
Para hacerlo en PowerShell, debes declarar la variable en la sesión y luego ejecutar el comando:

```powershell
# Forma correcta en PowerShell
$env:MI_VARIABLE="mi_valor"
docker-compose up -d
```
*(Si usas un archivo `.env`, Docker lo leerá automáticamente, así que esto solo es necesario para overrides rápidos).*

### 2. Rutas de Volúmenes en Windows
Si vas a mapear rutas absolutas en tu `docker-compose.yml`, PowerShell y Docker a veces se pelean con las barras.
* **Recomendación:** Usa siempre rutas relativas (`./data:/var/lib/data`).
* Si necesitas absoluta, usa la sintaxis de Docker para Windows: `C:/mi/ruta:/contenedor/ruta` (usa barras normales `/`, no invertidas `\`).

### 3. Alias en PowerShell
Si te cansas de escribir `docker-compose`, puedes crear un alias en tu perfil de PowerShell para usar el comando nativo V2 (que es más rápido):
```powershell
# Para probarlo en la sesión actual
Set-Alias dc docker

# Ahora puedes escribir:
dc compose up -d --build
```

---

## 📄 Ejemplo de `docker-compose.yml` para practicar

Si quieres probar los comandos, guarda esto como `docker-compose.yml` en tu carpeta:

```yaml
version: '3.8'

services:
  web:
    image: nginx:alpine
    ports:
      - "8080:80"
    volumes:
      - ./html:/usr/share/nginx/html
    environment:
      - NGINX_HOST=foobar.com

  redis:
    image: redis:alpine
    ports:
      - "6379:6379"
```

**Ruta de prueba recomendada:**
1. Crea una carpeta `html` al lado del yml y mete un `index.html` dentro.
2. Ejecuta: `docker-compose up -d`
3. Revisa el estado: `docker-compose ps`
4. Entra al redis: `docker-compose exec redis sh` (y escribe `ping`, debe responder `PONG`).
5. Baja todo: `docker-compose down`