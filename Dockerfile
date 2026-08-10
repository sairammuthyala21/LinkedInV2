FROM apify/actor-python:3.11

# Copy requirements first for layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the source code
COPY . ./

CMD ["python", "src/main.py"]