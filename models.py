from sqlalchemy import Column, Integer, String, Text, ForeignKey, UniqueConstraint
from database import Base

class MockDeployment(Base):
    __tablename__ = "mocks"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True)
    base_path = Column(String(50), unique=True)
    swagger_content = Column(Text)
    endpoints = Column(Text)

class EndpointResponse(Base):
    __tablename__ = "endpoint_responses"
    
    id = Column(Integer, primary_key=True, index=True)
    mock_id = Column(Integer, ForeignKey('mocks.id'))
    path = Column(String(500))
    method = Column(String(10))
    response_body = Column(Text)
    response_headers = Column(Text)
    
    __table_args__ = (
        UniqueConstraint('mock_id', 'path', 'method', name='_mock_path_method_uc'),
    )
