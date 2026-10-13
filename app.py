import os, io, logging
from urllib.parse import quote_plus
import boto3
import pandas as pd
from sqlalchemy import create_engine

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger()

REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
S3_BUCKET = os.environ["S3_BUCKET"]
CSV_KEY = os.environ["CSV_KEY"]
RDS_HOST = os.environ["RDS_HOST"]
RDS_USER = os.environ["RDS_USER"]
RDS_PASSWORD = os.environ["RDS_PASSWORD"]
RDS_DB = os.environ["RDS_DB"]
RDS_TABLE = os.environ["RDS_TABLE"]
GLUE_DB = os.environ["GLUE_DB"]
GLUE_TABLE = os.environ["GLUE_TABLE"]
GLUE_S3_LOCATION = os.environ["GLUE_S3_LOCATION"]

def read_csv_from_s3():
    s3 = boto3.client("s3", region_name=REGION)
    obj = s3.get_object(Bucket=S3_BUCKET, Key=CSV_KEY)
    return pd.read_csv(io.BytesIO(obj["Body"].read()))

def push_to_rds(df):
    url = (f"mysql+pymysql://{RDS_USER}:{quote_plus(RDS_PASSWORD)}"
           f"@{RDS_HOST}:3306/{RDS_DB}")
    engine = create_engine(url, connect_args={"connect_timeout": 10})
    df.to_sql(RDS_TABLE, engine, if_exists="append", index=False)

def fallback_to_glue(df):
    glue = boto3.client("glue", region_name=REGION)
    try:
        glue.create_database(DatabaseInput={"Name": GLUE_DB})
    except glue.exceptions.AlreadyExistsException:
        log.info("Glue database already exists")
    cols = [{"Name": c.strip().lower().replace(" ", "_"), "Type": "string"}
            for c in df.columns]
    try:
        glue.create_table(DatabaseName=GLUE_DB, TableInput={
            "Name": GLUE_TABLE,
            "TableType": "EXTERNAL_TABLE",
            "Parameters": {"classification": "csv",
                           "skip.header.line.count": "1"},
            "StorageDescriptor": {
                "Columns": cols,
                "Location": GLUE_S3_LOCATION,
                "InputFormat": "org.apache.hadoop.mapred.TextInputFormat",
                "OutputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
                "SerdeInfo": {
                    "SerializationLibrary": "org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe",
                    "Parameters": {"field.delim": ","}}}})
        log.info("Glue table created: %s.%s", GLUE_DB, GLUE_TABLE)
    except glue.exceptions.AlreadyExistsException:
        log.info("Glue table already exists")

def main():
    log.info("Reading s3://%s/%s", S3_BUCKET, CSV_KEY)
    df = read_csv_from_s3()
    log.info("Rows read: %d", len(df))
    try:
        push_to_rds(df)
        log.info("SUCCESS: data pushed to RDS table %s", RDS_TABLE)
    except Exception as e:
        log.error("RDS push failed: %s", e)
        log.info("Falling back to AWS Glue...")
        fallback_to_glue(df)

if __name__ == "__main__":
    main()
