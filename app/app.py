import os
import asyncio
import httpx

from random import randint
from bs4 import BeautifulSoup
from datetime import datetime
from aiogram import Bot, Dispatcher, executor, types
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConnectionFailure, DuplicateKeyError

# mongo_url = (f"mongodb://{os.environ['MONGODB_USERNAME']}:{os.environ['MONGODB_PASSWORD']}"
#              f"@{os.environ['MONGODB_HOSTNAME']}:27117/{os.environ['MONGODB_DATABASE']}")
# client = AsyncIOMotorClient(mongo_url)
# db = client.hh_bot
# coll = db.users

client = AsyncIOMotorClient(os.environ["MONGODB_HOSTNAME"])
db = client.hh_bot
coll = db.users

TOKEN = os.environ.get("TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

headers = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 5.1; rv:47.0) Gecko/20100101 Firefox/47.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    },
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 5.1) AppleWebKit/537.36 (KHTML, like Gecko)"
        "Chrome/49.0.2623.112 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    },
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 6.1; rv:53.0) Gecko/20100101 Firefox/53.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    },
]

user_tasks = {}


@dp.message_handler(commands=["start", "help"])
async def send_welcome(message: types.Message):
    await create_user(message)

    hello = """
Для поиска вакансии введите название города или региона (Россия, Украина, Казахстан, Молдавия и др.) 
и ключевые слова через @, например:

Москва @ python junior
Киев @ инженер
Республика Коми @ водитель

Проверка новых вакансий происходит каждые 30 минут.
Дубликаты вакансий повторно не будут высылаться.
Остановить поиск - команда "/stop".
Чтобы очистить историю вакансий, отправьте "/delete".
Для помощи пишите "/help".
        """
    await message.reply(hello)


@dp.message_handler(commands=["stop"])
async def stop(message: types.Message):
    await coll.update_one({"_id": message.chat.id}, {"$set": {"qs": []}})
    try:
        user_id = message.chat.id
        user_tasks[user_id].cancel()
        print("STOP TASK")
    except Exception as e:
        print(e)

    await message.answer(
        "Вы остановили поиск вакансий! Введите новые ключевые слова для продолжения!"
    )


@dp.message_handler(commands=["delete"])
async def delete(message: types.Message):
    await coll.update_one({"_id": message.chat.id}, {"$set": {"urls": []}})
    await message.answer("История ваших вакансий была очищена!")
    await stop(message)


@dp.message_handler(regexp="@")
async def main(message):
    global user_tasks
    user_id = message.chat.id

    if user_id in user_tasks:
        try:
            user_tasks[user_id].cancel()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(e)

    user_tasks[user_id] = asyncio.create_task(send_vacancy(message))


@dp.message_handler()
async def echo(message: types.Message):
    await message.answer(
        "You have entered an invalid request. Try again. For help, send /help"
    )


async def send_vacancy(message):
    city = await check_city(message)
    qs = await check_qs(message)

    if city and qs:
        try:
            await get_vacancy_hh(message)
        except Exception as e:
            print(f"Critical error: {str(e)}")
    else:
        await message.answer(
            "You have entered an invalid request. Try again. For help, send /help"
        )


async def create_user(message) -> None:
    try:
        await coll.insert_one(
            {
                "_id": message.chat.id,
                "name": message.chat.first_name,
                "username": message.chat.username,
                "city_id": 1,
                "qs": [],
                "urls": [],
                "time": datetime.now(),
            }
        )
    except DuplicateKeyError:
        pass


async def check_city(message):
    url = "https://api.hh.ru/areas"
    response = await async_request(url)

    if response.status_code == 200:
        areas = response.json()
        city_id = 1
        city_name = message.text.lower().split("@")[0].strip()

        for country in areas:
            for region in country["areas"]:
                if region["name"].lower() == city_name:
                    city_id = region["id"]

                for city in region["areas"]:
                    if city["name"].lower() == city_name:
                        city_id = city["id"]

        await coll.update_one({"_id": message.chat.id}, {"$set": {"city_id": city_id}})

        return city_id


async def check_qs(message):
    qs = message.text.lower().split("@")[1].strip().split()
    await coll.update_one({"_id": message.chat.id}, {"$set": {"qs": qs}})
    return qs


async def async_request(url):
    async with httpx.AsyncClient() as client:
        return await client.get(url, headers=headers[randint(0, 2)])


async def get_vacancy_hh(message):
    await message.answer("Ищем вакансии!")
    user = {}
    qs = []
    city_id = ""
    count = 0
    while True:
        try:
            user = await coll.find_one({"_id": message.chat.id})
            city_id = user.get("city_id", 1)
            qs = user.get("qs", [])
        except ConnectionFailure:
            await message.answer("Lost connection with DB!")

        if qs and user:
            vacancy = []
            vacancy_tmp = []
            vacancy_old = user.get("urls")
            words = "+".join(qs).lower()
            urls = [
                f"https://hh.ru/search/vacancy?area={city_id}&order_by=publication_time&"
                f"ored_clusters=true&text={words}&search_period=30&search_field=name"
            ]
            error_msg = "Сайт hh.ru не отвечает"
            for url in urls:
                response = await async_request(url)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, "html.parser")
                    main_div = soup.find_all(
                        "div", attrs={"class": "vacancy-serp-item-body__main-info"}
                    )
                    for div in main_div:
                        link = div.find("a", attrs={"class": "bloko-link"})
                        vacancy.append(link["href"].split("?")[0])
                else:
                    await message.answer(error_msg)
            for item in vacancy:
                if "feedback" and "article" and "click" not in item:
                    if item not in vacancy_old:
                        vacancy_tmp.append(item)
                        await message.answer(item)
            try:
                new_urls = {"$push": {"urls": {"$each": vacancy_tmp}}}
                await coll.update_one({"_id": message.chat.id}, new_urls)
            except ConnectionFailure:
                await message.answer("Lost connection with DB!")
            print("hh.ru:", datetime.now())
            count += 1
            await asyncio.sleep(1800)
            if count == 672:
                await coll.update_one({"_id": message.chat.id}, {"$set": {"qs": []}})
                break
        else:
            break
    await message.answer(
        "Поиск закончен. При необходимости вы можете продолжить поиск по новому запросу."
    )


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
