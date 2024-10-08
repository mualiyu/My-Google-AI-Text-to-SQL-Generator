from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
import os
import mysql.connector
import google.generativeai as genai
from mysql.connector import Error

# Load environment variables
load_dotenv()

# Configure Gemini AI
env_var = os.getenv('GOOGLE_API_KEY')
if env_var is None:
    raise EnvironmentError("GOOGLE_API_KEY not found in environment variables.")
genai.configure(api_key=env_var)

# Configure MySQL connection
db_config = {
    'host': os.getenv('MYSQL_HOST', 'localhost'),
    'user': os.getenv('MYSQL_USER'),
    'password': os.getenv('MYSQL_PASSWORD'),
    'database': os.getenv('MYSQL_DATABASE')
}

app = FastAPI()

class Query(BaseModel):
    query: str

def get_db_structure():
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("SHOW TABLES")
        tables = [table[0] for table in cursor.fetchall()]
        
        db_structure = {}
        for table in tables:
            cursor.execute(f"DESCRIBE {table}")
            columns = [column[0] for column in cursor.fetchall()]
            db_structure[table] = columns
        
        return db_structure
    except Error as e:
        print(f"Error reading database structure: {e}")
        return None
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()

def generate_prompt(db_structure):
    prompt = """
You are an expert in converting complex English questions to SQL queries and handling data insertion and update requests!
The SQL database has the following structure:

"""
    for table, columns in db_structure.items():
        prompt += f"{table} table columns: {', '.join(columns)}\n"
    
    prompt += """
Here are some examples to guide you:

Example 1 - How many registered users are there?
SQL: SELECT COUNT(*) FROM USERS;

Example 2 - List all product names with their prices.
SQL: SELECT name, price FROM PRODUCTS;

Example 3 - What's the total revenue from all orders?
SQL: SELECT SUM(total_price) FROM ORDERS;

Example 4 - Who are the top 5 customers by total spending?
SQL: SELECT u.username, SUM(o.total_price) AS total_spent
     FROM USERS u
     JOIN ORDERS o ON u.user_id = o.user_id
     GROUP BY u.user_id
     ORDER BY total_spent DESC
     LIMIT 5;

Example 5 - Which products are out of stock?
SQL: SELECT name FROM PRODUCTS WHERE stock_quantity = 0;

Example 6 - What's the average order value?
SQL: SELECT AVG(total_price) FROM ORDERS;

Example 7 - Add new user (name: John Doe, email: john@example.com)
SQL: INSERT INTO USERS (username, email) VALUES ('John Doe', 'john@example.com');

Example 8 - Add new product for John Doe (name: Laptop, price: 999.99, description: High-performance laptop, stock_quantity: 10)
SQL: 
INSERT INTO PRODUCTS (name, price, description, stock_quantity, user_id)
SELECT 'Laptop', 999.99, 'High-performance laptop', 10, user_id
FROM USERS
WHERE username = 'John Doe';

Example 9 - Update John Doe's email to newemail@example.com
SQL: UPDATE USERS SET email = 'newemail@example.com' WHERE username = 'John Doe';

Example 10 - Update the price of Laptop to 1099.99
SQL: UPDATE PRODUCTS SET price = 1099.99 WHERE name = 'Laptop';

Please convert the following question, insertion, or update request into a SQL query based on these tables and examples. For insertion or update requests, generate the appropriate INSERT or UPDATE statement. The SQL code should not have triple backticks (```) at the beginning or end, and should not include the word 'sql' in the output.
"""
    return prompt

def get_gemini_response(question):
    try:
        model = genai.GenerativeModel("gemini-pro")
        response = model.generate_content(prompt + question)
        return response.text
    except Exception as e:
        print(f"An error occurred while generating SQL: {e}")
        return None

def execute_sql_query(sql):
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        if sql.strip().upper().startswith(("INSERT", "UPDATE")):
            cursor.execute(sql)
            conn.commit()
            return {"message": "Data operation successful", "affected_rows": cursor.rowcount}
        else:
            cursor.execute(sql)
            results = cursor.fetchall()
            return results
    except mysql.connector.Error as e:
        print(f"A database error occurred: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()

@app.on_event("startup")
async def startup_event():
    global prompt
    db_structure = get_db_structure()
    if db_structure:
        prompt = generate_prompt(db_structure)
    else:
        print("Failed to read database structure. Using default prompt.")

@app.post("/api/query")
async def query_database(query: Query):
    sql_query = get_gemini_response(query.query)
    if not sql_query:
        raise HTTPException(status_code=500, detail="Failed to generate SQL query")
    
    # return {"sql_query": sql_query}
    results = execute_sql_query(sql_query)
    return {"sql_query": sql_query, "results": results}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
