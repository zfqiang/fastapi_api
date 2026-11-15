from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)


# 这是一个异步生成器函数，用于获取数据库会话
# 它接收一个Request类型的参数，返回一个异步迭代器，迭代器产生异步会话对象
async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    # 使用异步上下文管理器创建一个数据库会话
    # 会话从应用程序的状态中获取的会话工厂创建
    async with request.app.state.session_factory() as session:
        # 使用yield关键字将会话对象传递给调用者
        # 这是一种依赖注入的模式，常用于FastAPI等框架中
        try:
            yield session
        except Exception as e:
            await session.rollback()
            raise e
        finally:  # 不需要显式 close()，async with 退出时会自动关闭
            # 确保会话在迭代完成后被关闭
            await session.close()
