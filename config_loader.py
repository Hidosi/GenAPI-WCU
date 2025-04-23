import yaml
import threading

class ConfigLoader:
    _lock = threading.Lock()
    _config_data = None
    _config_path = 'config.yaml'  # путь к твоему файлу конфигурации

    @classmethod
    def load_config(cls):
        """
        Загрузить конфигурацию из файла, если ещё не загружена.
        Возвращает кэшированные данные при повторных вызовах.
        """
        with cls._lock:
            if cls._config_data is None:
                with open(cls._config_path, 'r', encoding='utf-8') as f:
                    cls._config_data = yaml.safe_load(f)
            return cls._config_data

    @classmethod
    def reload_config(cls):
        """
        Принудительно перезагрузить конфигурацию из файла.
        """
        with cls._lock:
            with open(cls._config_path, 'r', encoding='utf-8') as f:
                cls._config_data = yaml.safe_load(f)
            return cls._config_data