# Copilot Instructions for Virtual Exam Starter

## Project Requirements
- **Project Type**: Django virtual exam starter
- **Language**: Python
- **Database**: PostgreSQL via environment variables
- **Styling**: Tailwind CSS via CLI build

## Setup Instructions
1. **Clone the Repository**: 
   ```bash
   git clone <repository-url>
   cd virtual-exam-starter
   ```

2. **Create a Virtual Environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```

3. **Install Dependencies**:
   - Using Pipenv:
     ```bash
     pip install pipenv
     pipenv install
     ```
   - Or using requirements.txt:
     ```bash
     pip install -r backend/requirements.txt
     ```

4. **Set Up Environment Variables**:
   - Copy the `.env.example` to `.env` and fill in the required database configurations.

5. **Run Migrations**:
   ```bash
   python backend/manage.py migrate
   ```

6. **Run the Development Server**:
   ```bash
   python backend/manage.py runserver
   ```

## Frontend Setup
1. **Navigate to the Frontend Directory**:
   ```bash
   cd frontend
   ```

2. **Install Frontend Dependencies**:
   ```bash
   npm install
   ```

3. **Build Tailwind CSS**:
   ```bash
   npx tailwindcss -i ./src/input.css -o ./dist/output.css --watch
   ```

## Additional Tasks
- **Compile the Project**: Ensure all components are built and ready for deployment.
- **Create and Run Task**: Set up any necessary tasks for automated testing or deployment.
- **Launch the Project**: Deploy the application to a production environment.
- **Ensure Documentation is Complete**: Review and update documentation as necessary.

## Notes
- Initial scaffold created manually in the current workspace.
- Ensure to follow best practices for security, especially regarding environment variables and database configurations.