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
