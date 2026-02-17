"""
Admin API Endpoints
Provides management interfaces for knowledge base updates and system administration
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from typing import Optional, Dict, Any
import logging
import shutil
import os
from datetime import datetime
import json

from app.core.config import settings
from app.data.knowledge_integrator import integrated_knowledge

logger = logging.getLogger(__name__)

router = APIRouter()

# API Key Security (optional - configure ADMIN_API_KEY in .env)
api_key_header = APIKeyHeader(name="X-Admin-API-Key", auto_error=False)


def verify_admin_key(api_key: str = Security(api_key_header)):
    """Verify admin API key"""
    # If ADMIN_API_KEY not set in env, allow all requests (development mode)
    if not hasattr(settings, 'ADMIN_API_KEY') or not settings.ADMIN_API_KEY:
        logger.warning("⚠️ ADMIN_API_KEY not set - admin endpoints are unprotected!")
        return True
    
    if api_key != settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API key"
        )
    return True


class UploadResponse(BaseModel):
    """Response model for file uploads"""
    success: bool
    message: str
    tests_updated: Optional[int] = None
    backup_path: Optional[str] = None
    error: Optional[str] = None


class KnowledgeStatsResponse(BaseModel):
    """Response model for knowledge base statistics"""
    total_tests: int
    sources: Dict[str, int]
    categories: int
    services: int
    tests_with_prices: int
    tests_with_preparation: int
    tests_with_symptoms: int


@router.post("/admin/upload-excel", response_model=UploadResponse, summary="Upload Excel File to Update Knowledge Base")
async def upload_excel(
    file: UploadFile = File(..., description="Excel file (.xlsx) with test data"),
    _: bool = Depends(verify_admin_key)
):
    """
    Upload an Excel file to update the knowledge base
    
    **Process:**
    1. Validates file format (.xlsx)
    2. Saves temporary file
    3. Converts Excel to JSON
    4. Backs up current knowledge base
    5. Validates new data
    6. Updates knowledge base
    7. Reloads without server restart
    
    **Requires:** X-Admin-API-Key header (if ADMIN_API_KEY is configured)
    """
    try:
        # Validate file extension
        if not file.filename.endswith('.xlsx'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File must be an Excel file (.xlsx)"
            )
        
        logger.info(f"📤 Received Excel upload: {file.filename}")
        
        # Create uploads directory if not exists
        uploads_dir = os.path.join(os.path.dirname(__file__), "..", "data", "uploads")
        os.makedirs(uploads_dir, exist_ok=True)
        
        # Save uploaded file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_excel_path = os.path.join(uploads_dir, f"{timestamp}_{file.filename}")
        
        with open(temp_excel_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        logger.info(f"💾 Saved temporary file: {temp_excel_path}")
        
        # Convert Excel to JSON
        from app.data import simple_excel_converter
        
        temp_json_path = os.path.join(uploads_dir, f"{timestamp}_data.json")
        result = simple_excel_converter.excel_to_json(temp_excel_path, temp_json_path)
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to convert Excel file to JSON"
            )
        
        # Validate JSON structure
        if not result.get("Sheet1", {}).get("data"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Excel file does not contain valid test data"
            )
        
        # Backup current knowledge base
        backup_dir = os.path.join(os.path.dirname(__file__), "..", "data", "backups")
        os.makedirs(backup_dir, exist_ok=True)
        
        backup_path = os.path.join(backup_dir, f"knowledge_backup_{timestamp}.json")
        
        excel_data_path = os.path.join(os.path.dirname(__file__), "..", "data", "excel_data.json")
        if os.path.exists(excel_data_path):
            shutil.copy(excel_data_path, backup_path)
            logger.info(f"📦 Created backup: {backup_path}")
        
        # Replace excel_data.json with new data
        shutil.copy(temp_json_path, excel_data_path)
        logger.info(f"✅ Updated excel_data.json")
        
        # Reload knowledge base
        integrated_knowledge.load_all()
        integrated_knowledge.save_unified_knowledge()
        logger.info(f"🔄 Reloaded knowledge base")
        
        # Get updated stats
        stats = integrated_knowledge.get_stats()
        
        return UploadResponse(
            success=True,
            message=f"Successfully updated knowledge base from {file.filename}",
            tests_updated=stats["total_tests"],
            backup_path=backup_path,
            error=None
        )
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"❌ Error uploading Excel: {str(e)}", exc_info=True)
        return UploadResponse(
            success=False,
            message="Failed to upload and process Excel file",
            error=str(e)
        )


@router.get("/admin/knowledge-stats", response_model=KnowledgeStatsResponse, summary="Get Knowledge Base Statistics")
async def get_knowledge_stats(_: bool = Depends(verify_admin_key)):
    """
    Get comprehensive statistics about the knowledge base
    
    **Returns:**
    - Total number of tests
    - Tests by source (knowledge.json, Excel, merged)
    - Number of categories
    - Number of services
    - Tests with prices
    - Tests with preparation instructions
    - Tests with symptoms
    
    **Requires:** X-Admin-API-Key header (if ADMIN_API_KEY is configured)
    """
    try:
        stats = integrated_knowledge.get_stats()
        
        return KnowledgeStatsResponse(
            total_tests=stats["total_tests"],
            sources=stats["sources"],
            categories=stats["categories"],
            services=stats["services"],
            tests_with_prices=stats["tests_with_prices"],
            tests_with_preparation=stats["tests_with_preparation"],
            tests_with_symptoms=stats["tests_with_symptoms"]
        )
    
    except Exception as e:
        logger.error(f"❌ Error getting stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve knowledge base statistics"
        )


@router.post("/admin/reload-knowledge", summary="Reload Knowledge Base")
async def reload_knowledge(_: bool = Depends(verify_admin_key)):
    """
    Manually reload knowledge base from files without server restart
    
    **Use case:** After manually updating knowledge.json or excel_data.json
    
    **Requires:** X-Admin-API-Key header (if ADMIN_API_KEY is configured)
    """
    try:
        logger.info("🔄 Manually reloading knowledge base...")
        
        integrated_knowledge.load_all()
        integrated_knowledge.save_unified_knowledge()
        
        stats = integrated_knowledge.get_stats()
        
        return {
            "success": True,
            "message": "Knowledge base reloaded successfully",
            "stats": stats
        }
    
    except Exception as e:
        logger.error(f"❌ Error reloading knowledge: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reload knowledge base: {str(e)}"
        )


@router.get("/admin/backups", summary="List Knowledge Base Backups")
async def list_backups(_: bool = Depends(verify_admin_key)):
    """
    List all available knowledge base backups
    
    **Returns:**
    - List of backup files with timestamps
    - File sizes
    
    **Requires:** X-Admin-API-Key header (if ADMIN_API_KEY is configured)
    """
    try:
        backup_dir = os.path.join(os.path.dirname(__file__), "..", "data", "backups")
        
        if not os.path.exists(backup_dir):
            return {
                "success": True,
                "backups": [],
                "message": "No backups found"
            }
        
        backups = []
        for filename in os.listdir(backup_dir):
            if filename.endswith('.json'):
                file_path = os.path.join(backup_dir, filename)
                file_size = os.path.getsize(file_path)
                file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                
                backups.append({
                    "filename": filename,
                    "size_kb": round(file_size / 1024, 2),
                    "created_at": file_time.isoformat()
                })
        
        # Sort by creation time (newest first)
        backups.sort(key=lambda x: x["created_at"], reverse=True)
        
        return {
            "success": True,
            "backups": backups,
            "total": len(backups)
        }
    
    except Exception as e:
        logger.error(f"❌ Error listing backups: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list backups: {str(e)}"
        )


@router.post("/admin/restore-backup/{backup_filename}", summary="Restore Knowledge Base from Backup")
async def restore_backup(
    backup_filename: str,
    _: bool = Depends(verify_admin_key)
):
    """
    Restore knowledge base from a backup file
    
    **Process:**
    1. Validates backup file exists
    2. Creates backup of current state
    3. Restores from selected backup
    4. Reloads knowledge base
    
    **Requires:** X-Admin-API-Key header (if ADMIN_API_KEY is configured)
    """
    try:
        backup_dir = os.path.join(os.path.dirname(__file__), "..", "data", "backups")
        backup_path = os.path.join(backup_dir, backup_filename)
        
        # Validate backup exists
        if not os.path.exists(backup_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Backup file not found: {backup_filename}"
            )
        
        logger.info(f"📦 Restoring from backup: {backup_filename}")
        
        # Create backup of current state first
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        current_backup_path = os.path.join(backup_dir, f"pre_restore_backup_{timestamp}.json")
        
        excel_data_path = os.path.join(os.path.dirname(__file__), "..", "data", "excel_data.json")
        if os.path.exists(excel_data_path):
            shutil.copy(excel_data_path, current_backup_path)
            logger.info(f"📦 Created pre-restore backup: {current_backup_path}")
        
        # Restore from backup
        shutil.copy(backup_path, excel_data_path)
        logger.info(f"✅ Restored from backup")
        
        # Reload knowledge base
        integrated_knowledge.load_all()
        integrated_knowledge.save_unified_knowledge()
        
        stats = integrated_knowledge.get_stats()
        
        return {
            "success": True,
            "message": f"Successfully restored from backup: {backup_filename}",
            "stats": stats,
            "pre_restore_backup": current_backup_path
        }
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"❌ Error restoring backup: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restore backup: {str(e)}"
        )
