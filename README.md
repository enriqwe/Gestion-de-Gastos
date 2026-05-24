# Gestion de Gastos

Codigo para importar movimientos bancarios exportados desde ING y generar un dashboard estatico.

Este repositorio publica el codigo del dashboard y de los importadores. Los movimientos reales, Excel originales, HTML generado con datos, logs, entornos virtuales y caches quedan fuera del repositorio publico.

## Rutas

- Importador: `/home/flow/expenses-bot/import_movements.py`
- Comando habitual: `/home/flow/expenses-bot/import_and_generate.sh EXCEL.xls`
- Generador: `/home/flow/expenses-bot/generate_dashboard.py`
- Servidor local: `/home/flow/expenses-bot/dashboard_server.py`
- Dashboard generado localmente: `/home/flow/expenses-bot/gastos-repository/index.html`

## Uso

```bash
/home/flow/expenses-bot/import_and_generate.sh /ruta/al/excel.xls
```

El importador calcula una huella por cuenta, fecha, categoria, descripcion, comentario, importe y saldo. Si se importan dias solapados o el mismo Excel dos veces, los movimientos ya importados se cuentan como duplicados y no se vuelven a guardar.

Para servir el dashboard:

```bash
/home/flow/expenses-bot/start_dashboard.sh
```

El servidor exige login y usa SQLite local en `state/auth.sqlite3`, hashes de contraseña y enlaces de alta/restablecimiento enviados por email. Para crear o actualizar un usuario inicial:

```bash
python3 /home/flow/expenses-bot/dashboard_server.py init-user usuario@example.com 'contraseña'
```
