import React from 'react';
import { Button, Input, Upload } from 'antd';
import { Search, UserPlus, Upload as UploadIcon } from 'lucide-react';
import type { UploadProps } from 'antd';
import styles from './UserSearchBar.module.css';

type UserSearchBarProps = {
    searchValue: string;
    onSearchValueChange: (v: string) => void;
    onSearch: () => void;
    onCreateClick: () => void;
    onUpload: (file: File) => Promise<boolean>;
};

const UserSearchBar: React.FC<UserSearchBarProps> = ({
    searchValue,
    onSearchValueChange,
    onSearch,
    onCreateClick,
    onUpload,
}) => {
    const uploadProps: UploadProps = {
        showUploadList: false,
        beforeUpload: onUpload,
        accept: '.csv,.xlsx,.xls',
    };

    return (
        <div className={styles['user-search-bar']}>
            <Input.Search
                placeholder="搜索用户名或邮箱"
                value={searchValue}
                onChange={(e) => onSearchValueChange(e.target.value)}
                onSearch={onSearch}
                enterButton={<Search size={14} />}
                allowClear
            />
            <Button
                type="primary"
                icon={<UserPlus size={14} />}
                onClick={onCreateClick}
            >
                新建用户
            </Button>
            <Upload {...uploadProps}>
                <Button icon={<UploadIcon size={14} />}>批量导入</Button>
            </Upload>
        </div>
    );
};

export default UserSearchBar;
