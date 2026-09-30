# Cafe-Pérgamo

Proyecto desarrollado con **Django**.

## 🚀 Requisitos previos
- Python 3.12 o superior
- Git

## 🛠️ Instalación y ejecución local

1. **Clonar el repositorio:**
   ```bash
   git clone https://github.com/JFernandoMC-1151598/Cafe-Pergamo.git
   cd Cafe-Pergamo
   ```

2. **Crear y activar el entorno virtual:**
   - En Windows (PowerShell):
     ```powershell
     python -m venv venv
     .\venv\Scripts\Activate.ps1
     ```
   - En Linux / macOS:
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     ```

3. **Instalar dependencias:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configurar variables de entorno (Supabase / SQLite):**
   - Copiar la plantilla:
     ```powershell
     cp .env.example .env
     ```
   - Si dejas el archivo `.env` vacío o no lo creas, el proyecto utilizará **SQLite local** por defecto.
   - Para conectar con **Supabase**, abre `.env` y coloca tu cadena de conexión en `DATABASE_URL` (obtenida en *Project Settings -> Database -> Connection string*).

5. **Aplicar migraciones:**
   ```bash
   python manage.py migrate
   ```

6. **Iniciar el servidor de desarrollo:**
   ```bash
   python manage.py runserver
   ```
   Abrir en el navegador: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

## 🔐 Seguridad de contraseñas (RNF04 / HU01-ST4)

La subtarea **HU01-ST4 (SCRUM-61) "Implementar el cifrado"** pedía integrar
una librería como Bcrypt o Argon2 para que la contraseña nunca se
almacene en texto plano. En este proyecto ese requisito (RNF04) se
cumple por diseño, sin necesitar una librería adicional:

- La autenticación real —registro e inicio de sesión— la resuelve por
  completo **Supabase Auth (GoTrue)**, nunca Django directamente (ver
  la decisión de arquitectura documentada en `usuarios/views.py` y
  `usuarios/supabase_client.py`).
- Django **nunca guarda una contraseña en ninguna tabla propia**: el
  modelo `Usuario` no tiene campo de contraseña, y la única tabla de
  Django relacionada (`auth_user`, usada solo para la sesión) guarda
  la contraseña como *"no utilizable"* (`set_unusable_password()`),
  nunca un valor real ni un hash de la contraseña del usuario.
- La contraseña en texto plano solo viaja por HTTPS hacia Supabase
  Auth, que es quien la hashea con **bcrypt** internamente antes de
  guardarla en `auth.users` — una tabla que este proyecto ni siquiera
  modela ni puede leer directamente.

En resumen: no existe ningún punto de este código donde una
contraseña quede almacenada en texto plano, ni por nosotros ni por
Supabase. Agregar una librería de cifrado en Django sería cifrar un
dato que Django nunca llega a poseer.
