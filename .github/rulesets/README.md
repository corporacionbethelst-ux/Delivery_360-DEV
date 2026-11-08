# Protección de main preparada, pendiente de activar

`main.json` es una configuración revisable para GitHub Rulesets. Añadirla al
repositorio **no activa** la protección remota. La auditoría de la base confirmó
main sin protección y ningún ruleset activo; esta entrega no modifica settings.

Un administrador debe revisar/importar el JSON en los ajustes del repositorio:
protege la rama predeterminada, impide force-push y borrado, exige PR con una
aprobación y conversaciones resueltas, retira revisiones obsoletas y requiere
`release-readiness` con la rama actualizada. No hay bypass configurado.

El nombre del check corresponde al job de `.github/workflows/ci-cd.yml`. Confirmar
que existe una corrida antes de activar el requisito y verificar posteriormente
que un PR con ese check fallido no puede fusionarse. La cobertura actual mantiene
ese gate bloqueado; no reducir el umbral para forzar la activación o la release.

Configurar también revisores, ramas autorizadas y credenciales mínimas en los
environments staging/production. Son controles distintos del archivo ruleset.
