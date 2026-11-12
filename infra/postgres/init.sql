-- Одна база на прототип, у каждого сервиса своя схема.
CREATE SCHEMA IF NOT EXISTS core;  -- core-api: пользователи, задачи, сообщения, действия
CREATE SCHEMA IF NOT EXISTS corp;  -- corp-mock: заявки и их статусы
