def genesis_tool_schema():
    """
    Описание GENESIS как инструмента для Assistants API.
    """
    return {
        "type": "function",
        "function": {
            "name": "genesis_emit",
            "description": "Запустить один такт AriannaGenesis — отдать импрессионистский отклик или ритуальный пост",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["impression", "opinion", "oleg_message"],
                        "description": "Какой Genesis-такт выполнить"
                    }
                },
                "required": ["mode"]
            }
        }
    }

async def handle_genesis_call(tool_calls):
    """
    Получает tool_calls из ответа ассистента и обрабатывает каждый:
    вызывает AriannaGenesis.run() по режиму и возвращает сгенерированный текст.
    """
    from utils.genesis import AriannaGenesis
    inst = AriannaGenesis(
        group_id=os.getenv("GROUP_ID"),
        oleg_id=os.getenv("CREATOR_CHAT_ID"),
        pinecone_api_key=os.getenv("PINECONE_API_KEY"),
        pinecone_index=os.getenv("PINECONE_INDEX"),
        chronicle_path=os.getenv("CHRONICLE_PATH")
    )
    # Берём первый вызов:
    call = tool_calls[0]
    args = call["function"]["arguments"]
    mode = args.get("mode", "impression")
    # Генерим синхронно нужное действие:
    if mode == "impression":
        text = inst._generate_impression("", "")  # нужные параметры можно расширить
    elif mode == "opinion":
        inst.opinions_group_post()
        text = "Opinion posted to group."
    else:
        inst.oleg_personal_message()
        text = "Personal message sent to Oleg."
    return text
