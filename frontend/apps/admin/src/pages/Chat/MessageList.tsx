import React, { useEffect, useState, useRef } from 'react';
import { Input, Button, Spin, Empty, Avatar, Upload, message as antdMessage } from 'antd';
import { Send, Bot, User as UserIcon, Paperclip, AlertCircle, RotateCcw } from 'lucide-react';
import type { ChatMessage } from '../../types/chat';
import { uploadCSVAPI } from '../../api/upload';
import './MessageList.css';

const { TextArea } = Input;

interface MessageListProps {
    messages: ChatMessage[];
    streamingText: string;
    isStreaming: boolean;
    isLoading: boolean;
    onSend: (text: string) => void;
    onRetryFailedMessage?: (messageId: string) => void;
}

const MessageList: React.FC<MessageListProps> = ({
    messages,
    streamingText,
    isStreaming,
    isLoading,
    onSend,
    onRetryFailedMessage,
}) => {
    const [inputValue, setInputValue] = useState('');
    const messagesEndRef = useRef<HTMLDivElement>(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages, streamingText]);

    const handleSend = () => {
        const text = inputValue.trim();
        if (!text || isStreaming) return;
        onSend(text);
        setInputValue('');
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    const handleUpload = async (file: File) => {
        try {
            await uploadCSVAPI(file);
            antdMessage.success(`文件 ${file.name} 上传成功`);
        } catch {
            // error handled by interceptor
        }
        return false; // prevent default upload
    };

    const renderMessage = (msg: ChatMessage) => {
        const isUser = msg.role === 'user';
        return (
            <div key={msg.id} className={`chat-message ${isUser ? 'user' : 'assistant'}`}>
                <Avatar
                    className="chat-avatar"
                    style={{ backgroundColor: isUser ? '#e8f4fd' : '#f0f5ff', flexShrink: 0 }}
                    icon={isUser ? <UserIcon size={18} color="#1677ff" /> : <Bot size={18} color="#722ed1" />}
                />
                <div className={`chat-bubble ${isUser ? 'user-bubble' : 'assistant-bubble'}`}>
                    {msg.status === 'failed' ? (
                        <>
                            <div className="error-content">
                                <AlertCircle size={14} />
                                <span>{msg.content || '请求处理失败'}</span>
                            </div>
                            {!isUser && onRetryFailedMessage && (
                                <div className="error-actions">
                                    <Button
                                        type="link"
                                        className="retry-btn"
                                        icon={<RotateCcw size={14} />}
                                        onClick={() => onRetryFailedMessage(msg.id)}
                                        disabled={isStreaming}
                                    >
                                        重试
                                    </Button>
                                </div>
                            )}
                        </>
                    ) : (
                        <div className="message-text">{msg.content}</div>
                    )}
                    {msg.latency_ms && (
                        <div className="message-meta">{msg.latency_ms}ms</div>
                    )}
                </div>
            </div>
        );
    };

    return (
        <div className="message-list-container">
            <div className="messages-scroll">
                {isLoading ? (
                    <div className="messages-loading">
                        <Spin size="large" />
                        <p>加载历史消息...</p>
                    </div>
                ) : messages.length === 0 && !isStreaming ? (
                    <div className="messages-empty">
                        <Empty
                            image={Empty.PRESENTED_IMAGE_SIMPLE}
                            description={
                                <div className="empty-hint">
                                    <Bot size={48} color="#d9d9d9" />
                                    <h3>开始你的对话</h3>
                                    <p>在下方输入框中输入你的问题</p>
                                </div>
                            }
                        />
                    </div>
                ) : (
                    <>
                        {messages.map(renderMessage)}
                        {isStreaming && streamingText && (
                            <div className="chat-message assistant">
                                <Avatar
                                    className="chat-avatar"
                                    style={{ backgroundColor: '#f0f5ff', flexShrink: 0 }}
                                    icon={<Bot size={18} color="#722ed1" />}
                                />
                                <div className="chat-bubble assistant-bubble">
                                    <div className="message-text">
                                        {streamingText}
                                        <span className="cursor-blink">|</span>
                                    </div>
                                </div>
                            </div>
                        )}
                        {isStreaming && !streamingText && (
                            <div className="chat-message assistant">
                                <Avatar
                                    className="chat-avatar"
                                    style={{ backgroundColor: '#f0f5ff', flexShrink: 0 }}
                                    icon={<Bot size={18} color="#722ed1" />}
                                />
                                <div className="chat-bubble assistant-bubble">
                                    <div className="thinking-dots">
                                        <span></span><span></span><span></span>
                                    </div>
                                </div>
                            </div>
                        )}
                    </>
                )}
                <div ref={messagesEndRef} />
            </div>

            <div className="input-area">
                <div className="input-row">
                    <Upload
                        showUploadList={false}
                        beforeUpload={handleUpload}
                        accept=".csv,.xlsx,.xls"
                    >
                        <Button
                            className="upload-btn"
                            icon={<Paperclip size={18} />}
                            type="text"
                            title="上传文件"
                        />
                    </Upload>
                    <TextArea
                        className="chat-input"
                        value={inputValue}
                        onChange={(e) => setInputValue(e.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder="输入消息... (Shift+Enter 换行)"
                        autoSize={{ minRows: 1, maxRows: 4 }}
                        disabled={isStreaming}
                    />
                    <Button
                        className="send-btn"
                        type="primary"
                        icon={<Send size={18} />}
                        onClick={handleSend}
                        disabled={!inputValue.trim() || isStreaming}
                        loading={isStreaming}
                    />
                </div>
            </div>
        </div>
    );
};

export default MessageList;
