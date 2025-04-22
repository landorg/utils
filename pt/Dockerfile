FROM python:3.13-slim

# Set the working directory in the container
WORKDIR /app

# Make port 8080 available to the world outside this container
EXPOSE 5001

# Define environment variable
# ENV NAME World

COPY ./requirements.txt /app/requirements.txt

# Install any needed dependencies specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the current directory contents into the container at /app
COPY . /app

# Run app.py when the container launches
CMD ["python", "app.py"]


