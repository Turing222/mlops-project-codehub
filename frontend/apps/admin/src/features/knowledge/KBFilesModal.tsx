import React, { useEffect, useRef } from 'react';
import { Modal, Table, Button, Space, Tag, message, Popconfirm } from 'antd';
import { Database, FileText, Trash2, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../context/useAuth';
import type { KnowledgeFile } from '../../schemas/chat';
import {
    useDeleteKBFileMutation,
    useKBFilesQuery,
} from '../../query/hooks/knowledge';
import styles from './KBFilesModal.module.css';

interface KBFilesModalProps {
    visible: boolean;
    onClose: () => void;
}

const KBFilesModal: React.FC<KBFilesModalProps> = ({ visible, onClose }) => {
    const { t } = useTranslation();
    const { isAuthenticated } = useAuth();
    const listEnabled = visible && isAuthenticated;
    const {
        data: files = [],
        isFetching,
        isError,
        errorUpdatedAt,
    } = useKBFilesQuery({ enabled: listEnabled });
    const deleteMutation = useDeleteKBFileMutation();
    const lastNotifiedErrorAtRef = useRef(0);

    useEffect(() => {
        if (!listEnabled || !isError || !errorUpdatedAt) return;
        if (errorUpdatedAt === lastNotifiedErrorAtRef.current) return;
        lastNotifiedErrorAtRef.current = errorUpdatedAt;
        message.error(t('chat.load_kb_files_failed', '加载文件列表失败'));
    }, [listEnabled, isError, errorUpdatedAt, t]);

    const handleDelete = async (id: string) => {
        if (!isAuthenticated) return;
        try {
            await deleteMutation.mutateAsync(id);
            message.success(t('chat.delete_kb_file_success', '文件退库成功'));
        } catch (error) {
            console.error('Failed to delete KB file:', error);
            message.error(t('chat.delete_kb_file_failed', '文件退库失败'));
        }
    };

    const formatBytes = (bytes: number): string => {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    };

    const formatDate = (dateStr: string): string => {
        try {
            const d = new Date(dateStr);
            return new Intl.DateTimeFormat(undefined, {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
            }).format(d);
        } catch {
            return dateStr;
        }
    };

    const columns = [
        {
            title: t('chat.file_name', '文件名'),
            dataIndex: 'filename',
            key: 'filename',
            render: (text: string) => (
                <Space>
                    <FileText size={16} className={styles['file-icon']} />
                    <span className={styles['filename-text']}>{text}</span>
                </Space>
            ),
        },
        {
            title: t('chat.file_size', '大小'),
            dataIndex: 'file_size',
            key: 'file_size',
            render: (size: number) => formatBytes(size),
            width: 100,
        },
        {
            title: t('chat.upload_time', '上传时间'),
            dataIndex: 'created_at',
            key: 'created_at',
            render: (time: string) => formatDate(time),
            width: 180,
        },
        {
            title: t('chat.status', '解析状态'),
            dataIndex: 'status',
            key: 'status',
            width: 120,
            render: (status: string) => {
                const s = status.toUpperCase();
                if (s === 'READY' || s === 'SUCCESS') {
                    return (
                        <Tag color="success" icon={<CheckCircle2 size={12} style={{ verticalAlign: 'middle', marginRight: 4 }} />}>
                            {t('chat.status_ready', '就绪')}
                        </Tag>
                    );
                }
                if (s === 'FAILED') {
                    return (
                        <Tag color="error" icon={<AlertCircle size={12} style={{ verticalAlign: 'middle', marginRight: 4 }} />}>
                            {t('chat.status_failed', '失败')}
                        </Tag>
                    );
                }
                return (
                    <Tag color="processing" icon={<Loader2 size={12} className={styles['spinning-icon']} style={{ verticalAlign: 'middle', marginRight: 4 }} />}>
                        {s === 'UPLOADED' ? t('chat.status_uploaded', '已上传') :
                         s === 'PARSING' ? t('chat.status_parsing', '解析中') :
                         t('chat.status_chunking', '分块中')}
                    </Tag>
                );
            },
        },
        {
            title: t('chat.action', '操作'),
            key: 'action',
            width: 80,
            render: (_: unknown, record: KnowledgeFile) => (
                <Popconfirm
                    title={t('chat.delete_kb_file_confirm', '确定要彻底清除此文件及其所属的所有向量切片吗？此操作不可逆。')}
                    onConfirm={() => handleDelete(record.id)}
                    okText={t('chat.confirm', '确认')}
                    cancelText={t('chat.cancel', '取消')}
                    placement="left"
                    disabled={!isAuthenticated}
                >
                    <Button
                        type="text"
                        danger
                        disabled={!isAuthenticated}
                        icon={<Trash2 size={15} />}
                        className={styles['delete-btn']}
                    />
                </Popconfirm>
            ),
        },
    ];

    return (
        <Modal
            title={
                <Space className={styles['modal-title-container']}>
                    <Database size={18} className={styles['title-icon']} />
                    <span>{t('chat.manage_kb_files', '管理知识库文档')}</span>
                </Space>
            }
            open={visible}
            onCancel={onClose}
            footer={[
                <Button key="close" type="primary" onClick={onClose}>
                    {t('chat.close', '关闭')}
                </Button>
            ]}
            width={800}
            className={styles['kb-files-modal']}
            destroyOnClose
        >
            <Table
                dataSource={files}
                columns={columns}
                rowKey="id"
                loading={isFetching}
                pagination={{ pageSize: 8 }}
                className={styles['files-table']}
            />
        </Modal>
    );
};

export default KBFilesModal;
