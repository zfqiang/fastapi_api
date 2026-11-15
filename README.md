# FastAPI 异步 API

提供注册、登录、JWT 认证、刷新/注销令牌、个人信息、登录主页、Redis 请求限流、结构化请求日志、CORS 和健康检查。

## 使用 Docker Compose 启动

```powershell
Copy-Item .env.example .env
docker compose up --build
```

接口文档：<http://localhost:8000/docs>

Compose 会等待 MySQL 和 Redis 健康后运行 Alembic 迁移，再启动 API。MySQL 数据保存在 `mysql_data` 卷中。

## 本地启动

需要 Python 3.11+、MySQL 8+ 和 Redis 7+。

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

### 使用 Conda

项目的 Conda 配置只记录 Python 运行时；应用依赖统一由 `requirements.txt` 管理。

```powershell
conda env create -f environment.yml
conda activate fastapi
pip install -r requirements.txt
```

如果已经有名为 `fastapi` 的环境，可用 `conda env update -n fastapi -f environment.yml` 更新 Conda 依赖，再执行 `pip install -r requirements.txt`。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/auth/register` | 注册并返回 Access/Refresh Token |
| POST | `/api/v1/auth/login` | 登录 |
| POST | `/api/v1/auth/refresh` | 轮换 Refresh Token，旧令牌立即失效 |
| POST | `/api/v1/auth/logout` | 撤销 Refresh Token |
| GET | `/api/v1/users/me` | 当前用户（Bearer Access Token） |
| GET | `/api/v1/home` | 受保护的主页示例 |
| GET | `/health/live` | 存活检查 |
| GET | `/health/ready` | MySQL/Redis 就绪检查 |

认证请求使用 JSON。注册/登录示例：

```json
{"email":"user@example.com","password":"at-least-8-characters"}
```

刷新/注销示例：

```json
{"refresh_token":"<refresh-token>"}
```

限流按客户端 IP、HTTP 方法和路径计数；认证接口使用更严格的每分钟额度。生产环境应通过 `SECRET_KEY` 配置至少 32 位随机密钥，并将 CORS 来源限制为可信域名。若部署在反向代理之后，需在可信代理边界配置客户端 IP 传递策略；当前默认不信任 `X-Forwarded-For`。

## 测试

```powershell
pip install pytest
pytest
```


## 团队成员（clone 后复现）
```
# 2. 用声明文件复现 conda 环境
conda env create -f environment.yml
conda activate myproj

# 3. 如有 pip 层依赖
pip install -r requirements.txt
```