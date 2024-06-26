import boto3
import json
import os
from aws_lambda_powertools import Logger
from langchain_community.chat_models import BedrockChat
from langchain_community.embeddings.bedrock import BedrockEmbeddings
from langchain.chains import ConversationalRetrievalChain
from langchain.memory import ConversationBufferMemory
from langchain.memory.chat_message_histories import DynamoDBChatMessageHistory
from langchain_community.vectorstores import FAISS

MEMORY_TABLE = os.environ["MEMORY_TABLE"]
BUCKET = os.environ["BUCKET"]


s3 = boto3.client("s3")
logger = Logger()


@logger.inject_lambda_context(log_event=True)
def lambda_handler(event, context):
    event_body = json.loads(event["body"])
    file_name = event_body["fileName"]
    human_input = event_body["prompt"]
    conversation_id = event["pathParameters"]["conversationid"]

    user = event["requestContext"]["authorizer"]["claims"]["sub"]

    s3.download_file(BUCKET, f"{user}/{file_name}/index.faiss", "/tmp/index.faiss")
    s3.download_file(BUCKET, f"{user}/{file_name}/index.pkl", "/tmp/index.pkl")

    bedrock_runtime = boto3.client(
        service_name="bedrock-runtime",
        region_name="us-east-1",
    )


    model_kwargs =  { 
    "max_tokens": 2048,  # Claude-3 use “max_tokens” However Claud-2 requires “max_tokens_to_sample”.
    "temperature": 0.0,
    "top_k": 250,
    "top_p": 1,
    "stop_sequences": ["\n\nHuman"],
    }


    embeddings = BedrockEmbeddings(
        model_id="amazon.titan-embed-text-v2:0"
    )
    
    chat = BedrockChat(
        model_id="anthropic.claude-3-sonnet-20240229-v1:0", 
        model_kwargs=model_kwargs,
    )

    faiss_index = FAISS.load_local("/tmp", embeddings, allow_dangerous_deserialization=True)

    message_history = DynamoDBChatMessageHistory(
        table_name=MEMORY_TABLE, session_id=conversation_id
    )

    memory = ConversationBufferMemory(
        memory_key="chat_history",
        chat_memory=message_history,
        input_key="question",
        output_key="answer",
        return_messages=True,
    )

    qa = ConversationalRetrievalChain.from_llm(
        llm=chat,
        retriever=faiss_index.as_retriever(),
        memory=memory,
        return_source_documents=True,
    )

    res = qa({"question": human_input})

    logger.info(res)

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
        },
        "body": json.dumps(res["answer"]),
    }
