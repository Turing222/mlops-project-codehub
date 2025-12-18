import chainlit as cl
import asyncio

# --- Domain Logic Stubs (模拟业务逻辑) ---
# In Phase 3, we will replace these with real imports from app.services
async def mock_rag_search(query: str):
    """
    Simulates searching the vector database.
    """
    await asyncio.sleep(1) # Simulate network latency (Latency Simulation)
    return [
        {"source": "Python装饰器.md", "content": "装饰器本质是闭包...", "score": 0.92},
        {"source": "Docker网络原理.md", "content": "Bridge模式是默认网络...", "score": 0.85}
    ]

# --- The UI Logic (Frontend) ---

@cl.on_chat_start
async def start():
    """
    Event: Triggered when a new user session starts.
    Use this to initialize user session or send a welcome message.
    """
    # Send a Welcome Message
    await cl.Message(
        content="👋 Welcome aboard! I am your Obsidian Mentor AI.\n\n"
                "I am currently running in **Dev Mode** (Stubbed Logic). "
                "The infrastructure is healthy!"
    ).send()

@cl.step(type="tool", name="🔍 Retrieval")
async def retrieval_step(query: str):
    """
    This decorated function will appear as a collapsible "Step" in the UI.
    This is your "X-Ray" feature for debugging.
    """
    # 1. Call the (mock) search logic
    docs = await mock_rag_search(query)
    
    # 2. Update the Step UI with input/output data
    current_step = cl.context.current_step
    current_step.input = query
    current_step.output = str(docs) # This shows the raw data in the UI expander
    
    return docs

@cl.on_message
async def main(message: cl.Message):
    """
    Event: Triggered every time the user sends a message.
    This is the Main Event Loop.
    """
    user_query = message.content

    # 1. Trigger the Retrieval Step (Visible in UI)
    retrieved_docs = await retrieval_step(user_query)

    # 2. Simulate LLM Generation (Visible in UI as streaming text)
    msg = cl.Message(content="")
    await msg.send()
    
    # Stream the response token by token (Simulating LLM streaming)
    fake_response = f"Based on your note `{retrieved_docs[0]['source']}`, here is the answer..."
    
    for char in fake_response:
        await msg.stream_token(char)
        await asyncio.sleep(0.05) # Simulate token generation speed

    await msg.update()