# Virtual Exam Starter

This project is a Django-based virtual exam platform designed to facilitate online examinations. It utilizes PostgreSQL for database management and Tailwind CSS for styling.

## Project Structure

```
virtual-exam-starter
├── .github
│   └── copilot-instructions.md
├── .gitignore
├── README.md
├── docker-compose.yml
├── Dockerfile
├── backend
│   ├── manage.py
│   ├── Pipfile
│   ├── requirements.txt
│   ├── .env.example
│   ├── virtual_exam
│   │   ├── __init__.py
│   │   ├── asgi.py
│   │   ├── settings.py
│   │   ├── urls.py
│   │   └── wsgi.py
│   ├── exams
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   ├── apps.py
│   │   ├── models.py
│   │   ├── views.py
│   │   ├── urls.py
│   │   ├── serializers.py
│   │   └── tests
│   │       └── test_models.py
│   └── templates
│       └── base.html
└── frontend
    ├── package.json
    ├── tailwind.config.js
    ├── postcss.config.js
    └── src
        ├── input.css
        └── main.js
```

## Requirements

- Python 3.x
- Django
- PostgreSQL
- Tailwind CSS

## Setup Instructions

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd virtual-exam-starter
   ```

2. **Set up the backend:**
   - Navigate to the `backend` directory.
   - Create a virtual environment and activate it.
   - Install dependencies:
     ```bash
     pip install -r requirements.txt
     ```

3. **Configure environment variables:**
   - Copy `.env.example` to `.env` and update the database settings.

4. **Run migrations:**
   ```bash
   python manage.py migrate
   ```

5. **Start the development server:**
   ```bash
   python manage.py runserver
   ```

6. **Set up the frontend:**
   - Navigate to the `frontend` directory.
   - Install Node.js dependencies:
     ```bash
     npm install
     ```

7. **Build the frontend:**
   ```bash
   npm run build
   ```

## Usage

- Access the application at `http://127.0.0.1:8000/`.
- Admin interface can be accessed at `http://127.0.0.1:8000/admin/`.

## License

This project is licensed under the MIT License. See the LICENSE file for more details.