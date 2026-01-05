import React, { useState, useRef } from 'react'
import { Upload, X, File, AlertCircle } from 'lucide-react'
import './FileUpload.css'

function FileUpload({ files, onFilesChange }) {
  const [isDragging, setIsDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)
  const fileInputRef = useRef(null)

  const handleDragOver = (e) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = (e) => {
    e.preventDefault()
    setIsDragging(false)
  }

  const handleDrop = async (e) => {
    e.preventDefault()
    setIsDragging(false)
    const droppedFiles = Array.from(e.dataTransfer.files)
    await uploadFiles(droppedFiles)
  }

  const handleFileSelect = async (e) => {
    const selectedFiles = Array.from(e.target.files)
    await uploadFiles(selectedFiles)
    e.target.value = ''
  }

  const uploadFiles = async (filesToUpload) => {
    setUploading(true)
    setError(null)

    for (const file of filesToUpload) {
      try {
        const formData = new FormData()
        formData.append('file', file)

        const response = await fetch('/upload', {
          method: 'POST',
          body: formData,
        })

        const text = await response.text()
        let data
        try {
          data = JSON.parse(text)
        } catch {
          throw new Error(text || '服务器响应异常')
        }

        if (!response.ok) {
          throw new Error(data.detail || '上传失败')
        }

        onFilesChange((prev) => [...prev, data])
      } catch (err) {
        setError(`${file.name}: ${err.message}`)
      }
    }

    setUploading(false)
  }

  const removeFile = async (fileId) => {
    try {
      await fetch(`/upload/${fileId}`, { method: 'DELETE' })
      onFilesChange((prev) => prev.filter((f) => f.file_id !== fileId))
    } catch (err) {
      console.error('删除文件失败:', err)
    }
  }

  const formatSize = (bytes) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  return (
    <div className="file-upload">
      <div
        className={`drop-zone ${isDragging ? 'dragging' : ''} ${uploading ? 'uploading' : ''}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
      >
        <Upload size={20} />
        <span>{uploading ? '上传中...' : '拖拽文件或点击上传'}</span>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={handleFileSelect}
          style={{ display: 'none' }}
        />
      </div>

      {error && (
        <div className="upload-error">
          <AlertCircle size={14} />
          <span>{error}</span>
        </div>
      )}

      {files.length > 0 && (
        <div className="file-list">
          {files.map((file) => (
            <div key={file.file_id} className="file-item">
              <File size={14} />
              <span className="file-name" title={file.filename}>
                {file.filename}
              </span>
              <span className="file-size">{formatSize(file.size)}</span>
              <button
                className="remove-btn"
                onClick={(e) => {
                  e.stopPropagation()
                  removeFile(file.file_id)
                }}
              >
                <X size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default FileUpload
