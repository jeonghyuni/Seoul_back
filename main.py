import os
import json
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv
import openai

# .env 파일 로드
load_dotenv()

# OpenAI API 키 설정
openai.api_key = os.getenv("OPENAI_API_KEY")

# 1. 데이터베이스(SQLite) 및 SQLAlchemy ORM 설정
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./localhub.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 2. DB 테이블 스키마(모델) 정의
class Location(Base):
    __tablename__ = "locations"
    
    id = Column(Integer, primary_key=True, index=True)
    contentid = Column(String, unique=True, index=True) # 공공데이터 고유 ID
    contenttypeid = Column(String, index=True)          # 유형 ID (12:관광지, 39:음식점 등)
    category = Column(String, index=True)               # 한국어 유형명 (관광지, 음식점 등)
    title = Column(String, index=True)                  # 장소명
    addr1 = Column(String)                              # 기본 주소
    addr2 = Column(String)                              # 상세 주소
    tel = Column(String)                                # 전화번호
    mapx = Column(String)                               # 경도
    mapy = Column(String)                               # 위도
    firstimage = Column(String)                         # 대표 이미지 URL
    cpyrhtDivCd = Column(String)                        # 공공누리 저작권 유형 (예: Type1)

class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    content = Column(Text)
    password = Column(String)                           # 요구사항: 평문 저장
    created_at = Column(DateTime, default=datetime.utcnow)

# DB 테이블 생성
Base.metadata.create_all(bind=engine)

# DB 세션 의존성 함수
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 3. 제공받은 JSON 파일 데이터를 SQLite DB에 파일 적재하는 로직
def seed_tour_data():
    db = SessionLocal()
    
    # 1. 중복 적재 방지
    if db.query(Location).count() > 0:
        print("[알림] DB에 이미 데이터가 존재하여 추가 적재를 건너뜁니다.")
        db.close()
        return

    # 2. 현재 실행 경로 디버깅 정보 출력 (매우 중요!)
    current_working_dir = os.path.abspath(os.getcwd())
    print("\n==================================================")
    print(f"[디버그] 현재 터미널 실행 위치(현재 폴더): {current_working_dir}")
    print(f"[디버그] 현재 폴더 내부 파일들: {os.listdir('.')}")
    
    # 상위 폴더도 분석해봅니다.
    parent_dir = os.path.abspath(os.path.join(".."))
    print(f"[디버그] 한 단계 위 상위 폴더: {parent_dir}")
    if os.path.exists(parent_dir):
        try:
            print(f"[디버그] 상위 폴더 내부 파일/폴더 목록: {os.listdir(parent_dir)}")
        except Exception as e:
            print(f"[디버그] 상위 폴더 목록 읽기 실패: {str(e)}")
    print("==================================================\n")

    # 3. 경로 후보군 설정
    # localhub-backend와 '서울' 폴더가 워크스페이스 상에서 어떤 관계든 다 찾을 수 있도록 후보를 넓힙니다.
    search_paths = [
        os.path.abspath(os.path.join("..", "서울")), # 1순위: 상위 폴더의 '서울'
        os.path.abspath("서울"),                     # 2순위: 현재 폴더 안의 '서울'
        os.path.abspath(os.path.join("data", "서울")),# 3순위: data/서울
        os.path.abspath(".")                         # 4순위: 현재 폴더 자체
    ]

    target_dir = None
    for path in search_paths:
        if os.path.exists(path):
            # 해당 폴더 안에 .json 파일이 실제로 들어있는지 확인
            try:
                files = os.listdir(path)
                json_files = [f for f in files if f.endswith(".json")]
                if json_files:
                    target_dir = path
                    print(f"[찾음!] 데이터를 가져올 타겟 폴더를 발견했습니다: {target_dir}")
                    print(f"       -> 발견된 JSON 파일들: {json_files}")
                    break
            except Exception:
                continue

    location_objects = []
    loaded_files_count = 0

    # 4. 파일 읽기 및 적재
    if target_dir and os.path.exists(target_dir):
        for file in os.listdir(target_dir):
            if file.endswith(".json"):
                file_path = os.path.join(target_dir, file)
                loaded_files_count += 1
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        
                    category_name = data.get("contentType", file.replace(".json", "").replace("서울_", ""))
                    items = data.get("items", [])
                    
                    for item in items:
                        if not item.get("title"):
                            continue
                        
                        loc = Location(
                            contentid=item.get("contentid"),
                            contenttypeid=item.get("contenttypeid"),
                            category=category_name,
                            title=item.get("title"),
                            addr1=item.get("addr1", ""),
                            addr2=item.get("addr2", ""),
                            tel=item.get("tel", ""),
                            mapx=item.get("mapx", "0.0"),
                            mapy=item.get("mapy", "0.0"),
                            firstimage=item.get("firstimage", ""),
                            cpyrhtDivCd=item.get("cpyrhtDivCd", "Type1")
                        )
                        location_objects.append(loc)
                    print(f"[성공] {file} 파싱 완료 ({len(items)}개 데이터)")
                except Exception as e:
                    print(f"[오류] {file} 파일 읽기 실패: {str(e)}")

    # 5. 안전장치용 임시 데이터 빌드
    if loaded_files_count == 0:
        print("[경고] 어떤 경로에서도 .json 파일을 찾지 못했습니다.")
        dummy = Location(
            contentid="1059877", contenttypeid="12", category="관광지",
            title="양화한강공원(임시)", addr1="서울특별시 영등포구 노들로 221", addr2="",
            tel="", mapx="126.9023658810", mapy="37.5382819489",
            firstimage="", cpyrhtDivCd="Type1"
        )
        db.add(dummy)
        db.commit()
        db.close()
        return

    # 6. DB 일괄 저장
    if location_objects:
        try:
            db.add_all(location_objects)
            db.commit()
            print(f"\n★ [최종 성공] 총 {loaded_files_count}개의 파일에서 {len(location_objects)}행을 DB에 완벽히 저장 완료했습니다! ★")
        except Exception as e:
            print(f"[오류] DB 저장 중 에러 발생: {str(e)}")
            db.rollback()
            
    db.close()

# 서버 구동 시 즉시 데이터 적재기 작동
seed_tour_data()

# 4. FastAPI 앱 초기화 및 CORS 설정
app = FastAPI(title="LocalHub Seoul API Server (TourAPI 4.0 Verified)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 5. Pydantic DTO 정의
class PostCreate(BaseModel):
    title: str
    content: str
    password: str

class PostUpdate(BaseModel):
    title: str
    content: str
    password: str

class PostDelete(BaseModel):
    password: str

class ChatRequest(BaseModel):
    message: str

# 6. 커뮤니티 익명 CRUD API 구현

# =================================================================
# [추가] 7개 카테고리 전체 통합 지원 - 지역 장소 정보 조회 API
# =================================================================

# 1. 카테고리별 장소 목록 조회 API (관광지, 레포츠, 쇼핑, 숙박 등 전체 지원)
@app.get("/api/locations")
def get_locations(category: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Location)
    
    # 프론트가 특정 카테고리를 주면 DB에서 필터링해서 제공
    if category:
        # 프론트엔드가 '맛집'이나 '축제·행사' 등 화면 한글 표기와 다르게 호출할 때 매핑해주는 안전장치
        if category == "맛집":
            category = "음식점"
        elif category in ["축제·행사", "축제", "축제공연행사"]:
            category = "축제공연행사"
            
        query = query.filter(Location.category == category)
    
    # 데이터가 너무 많으면 프론트가 렉 걸리므로, 우선 최대 100개만 가져오게 제한합니다.
    return query.limit(100).all()


# 2. 특정 장소의 상세 정보만 조회하는 API (필요 시 연동)
@app.get("/api/locations/{location_id}")
def get_location_detail(location_id: int, db: Session = Depends(get_db)):
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise HTTPException(status_code=404, detail="장소 정보를 찾을 수 없습니다.")
    return location

############추가완료

@app.get("/api/posts")
def get_posts(db: Session = Depends(get_db)):
    return db.query(Post).order_by(Post.created_at.desc()).all()

@app.get("/api/posts/{post_id}")
def get_post_detail(post_id: int, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    return post

@app.post("/api/posts", status_code=status.HTTP_201_CREATED)
def create_post(post_data: PostCreate, db: Session = Depends(get_db)):
    new_post = Post(
        title=post_data.title,
        content=post_data.content,
        password=post_data.password
    )
    db.add(new_post)
    db.commit()
    db.refresh(new_post)
    return {"message": "게시글이 성공적으로 등록되었습니다.", "post_id": new_post.id}

@app.put("/api/posts/{post_id}")
def update_post(post_id: int, post_data: PostUpdate, db: Session = Depends(get_db)):
    db_post = db.query(Post).filter(Post.id == post_id).first()
    if not db_post:
        raise HTTPException(status_code=404, detail="게시글이 존재하지 않습니다.")
    
    if db_post.password != post_data.password:
        raise HTTPException(status_code=403, detail="비밀번호가 일치하지 않아 권한이 없습니다.")
    
    db_post.title = post_data.title
    db_post.content = post_data.content
    db.commit()
    return {"message": "게시글이 성공적으로 수정되었습니다."}

@app.delete("/api/posts/{post_id}")
def delete_post(post_id: int, data: PostDelete, db: Session = Depends(get_db)):
    db_post = db.query(Post).filter(Post.id == post_id).first()
    if not db_post:
        raise HTTPException(status_code=404, detail="게시글이 존재하지 않습니다.")
    
    if db_post.password != data.password:
        raise HTTPException(status_code=403, detail="비밀번호가 일치하지 않아 권한이 없습니다.")
    
    db.delete(db_post)
    db.commit()
    return {"message": "게시글이 성공적으로 삭제되었습니다."}


# 7. 챗봇 기능 구현 (POST /api/chat) ─ 수집된 TourAPI 실제 기반 RAG 데이터 바인딩
@app.post("/api/chat")
def chat_with_local_data(chat_req: ChatRequest, db: Session = Depends(get_db)):
    user_message = chat_req.message
    
    # DB에서 최신 장소 데이터 20개 정도 긁어와서 프롬프트 컨텍스트 생성 (부하 방지)
    locations = db.query(Location).limit(30).all()
    context_str = ""
    for loc in locations:
        context_str += f"- [{loc.category}] {loc.title} | 주소: {loc.addr1} {loc.addr2} | 전화번호: {loc.tel}\n"
    
    system_prompt = (
        "너는 LocalHub 서비스의 서울 지역 전문 관광 및 커뮤니티 안내 챗봇이야.\n"
        "아래 제공된 [서울 지역 실제 공공데이터]를 철저히 참조하여 사용자의 질문에 친절하고 상세하게 한국어로 대답해줘.\n"
        "만약 리스트에 없는 장소나 정보를 유저가 물어본다면 가짜 정보를 만들어내지 말고, 모른다고 말하거나 아는 선에서 유연하게 대답해줘.\n\n"
        "[서울 지역 실제 공공데이터]\n"
        f"{context_str}"
    )
    
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.6
        )
        ai_reply = response.choices[0].message['content']
        return {"reply": ai_reply}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"챗봇 연동 실패: {str(e)}")