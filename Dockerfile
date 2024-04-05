# Use an official Python runtime as a parent image
FROM python:3.10

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app/

# Create and activate a virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN /opt/venv/bin/python -m pip install --upgrade pip

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create Django project and copy necessary files
RUN django-admin startproject config .
RUN cp example-config/urls.py config/urls.py
RUN cp example-config/settings.py config/settings.py

# Replace the Django secret key in .env
RUN sed -i "s/your_secret_key_here/$(grep -oP "SECRET_KEY = '\K[^']+" config/settings.py)/" .env

# Expose port 8000 to the outside world
EXPOSE 8000

# Run the web server
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
