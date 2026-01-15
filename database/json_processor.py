import json
import os
import glob
import re
from pathlib import Path
from typing import Optional, List, Dict, Any
from collections import Counter

class DataNormalizer:
    """データ正規化処理クラス"""
    
    @staticmethod
    def normalize_games(games_str: str) -> Optional[int]:
        """G数の正規化：カンマ除去して整数に変換"""
        if not games_str or games_str.strip() == "" or games_str == "-":
            return 0  # 実測値として0を返す
        
        try:
            # カンマを除去して整数に変換
            normalized = int(games_str.replace(",", ""))
            return normalized
        except (ValueError, AttributeError):
            raise ValueError(f"G数の変換に失敗: {games_str}")
    
    @staticmethod
    def normalize_diff_coins(diff_str: str) -> Optional[int]:
        """差枚の正規化：+/- 処理して整数に変換"""
        if not diff_str or diff_str.strip() == "" or diff_str == "-":
            return 0  # 実測値として0を返す
        
        try:
            # +/- 記号を考慮して変換
            cleaned = diff_str.replace(",", "").replace("+", "")
            normalized = int(cleaned)
            return normalized
        except (ValueError, AttributeError):
            raise ValueError(f"差枚の変換に失敗: {diff_str}")
    
    @staticmethod
    def normalize_count(count_str: str) -> int:
        """BB/RB回数の正規化"""
        if not count_str or count_str.strip() == "" or count_str == "-":
            return 0
        
        try:
            return int(count_str)
        except (ValueError, AttributeError):
            raise ValueError(f"回数の変換に失敗: {count_str}")
    
    @staticmethod
    def normalize_probability(prob_str: str) -> tuple[Optional[str], Optional[float]]:
        """確率の正規化：分数形式と小数形式の両方を返す"""
        if not prob_str or prob_str.strip() == "" or prob_str == "-":
            return None, None
        
        try:
            # 分数形式を保持
            fraction = prob_str.strip()
            
            # 1/XXX.X 形式から小数に変換
            if "/" in fraction:
                parts = fraction.split("/")
                if len(parts) == 2 and parts[0] == "1":
                    denominator = float(parts[1])
                    
                    # 分母が0の場合（未稼働台など）
                    if denominator == 0.0:
                        return fraction, None
                    
                    decimal = 1.0 / denominator
                    # 小数点以下6桁で丸める
                    decimal = round(decimal, 6)
                    return fraction, decimal
            
            # 分数形式でない場合はエラー
            raise ValueError(f"想定外の確率形式: {prob_str}")
            
        except (ValueError, AttributeError):
            raise ValueError(f"確率の変換に失敗: {prob_str}")
        except ZeroDivisionError:
            # 分母0の場合（既に上でチェック済みだが念のため）
            return fraction, None
    
    @staticmethod
    def normalize_machine_number(machine_num_str: str) -> int:
        """台番号の正規化：整数に変換"""
        if not machine_num_str or machine_num_str.strip() == "":
            raise ValueError("台番号が欠損しています")
        
        try:
            return int(machine_num_str)
        except (ValueError, AttributeError):
            raise ValueError(f"台番号の変換に失敗: {machine_num_str}")
    
    @staticmethod
    def calculate_last_digit_and_zorome(machine_number: int) -> tuple[str, bool]:
        """台番号から末尾1桁とゾロ目フラグを計算"""
        # 台番号を文字列に変換
        machine_str = str(machine_number)
        
        # 末尾1桁を取得
        last_digit = machine_str[-1]
        
        # 末尾2桁を取得してゾロ目判定
        if len(machine_str) < 2:
            # 1桁の場合は先頭に0を追加（例：5 → "05"）
            last_two_digits = "0" + machine_str
        else:
            last_two_digits = machine_str[-2:]
        
        # ゾロ目判定（末尾2桁が同じ）
        is_zorome = last_two_digits[0] == last_two_digits[1]
        
        return last_digit, is_zorome
    
    @staticmethod
    def calculate_games_deviation(games_normalized: int, avg_games_per_machine: int) -> int:
        """回転数偏差を計算（店舗平均との差）- 整数同士の演算"""
        if avg_games_per_machine is None or avg_games_per_machine == 0:
            return 0
        
        # 整数同士の演算なので精度問題なし
        deviation = games_normalized - avg_games_per_machine
        return deviation

class MachineCountCalculator:
    """同機種台数計算クラス"""
    
    def __init__(self):
        self.machine_counts = {}
        self.machine_rankings = {}
        self.machine_name_list = []
    
    def calculate_same_machine_counts(self, machine_data_list: List[Dict[str, Any]]) -> None:
        """同機種台数と順位を計算（その日の全機種名を自動抽出）"""
        # 機種別台数をカウント
        machine_name_counter = Counter()
        machine_numbers_by_type = {}
        
        for data in machine_data_list:
            machine_name = data["machine_name"]
            machine_number = data["machine_number"]
            
            machine_name_counter[machine_name] += 1
            
            if machine_name not in machine_numbers_by_type:
                machine_numbers_by_type[machine_name] = []
            machine_numbers_by_type[machine_name].append(machine_number)
        
        # 同機種台数を保存
        self.machine_counts = dict(machine_name_counter)
        
        # その日の機種名リストを保存（台数順でソート）
        self.machine_name_list = sorted(
            self.machine_counts.keys(), 
            key=lambda x: self.machine_counts[x], 
            reverse=True
        )
        
        # 機種内順位を計算（台番号昇順）
        self.machine_rankings = {}
        for machine_name, numbers in machine_numbers_by_type.items():
            sorted_numbers = sorted(numbers)
            for rank, number in enumerate(sorted_numbers, 1):
                self.machine_rankings[number] = rank
    
    def get_same_machine_count(self, machine_name: str) -> int:
        """指定機種の台数を取得"""
        return self.machine_counts.get(machine_name, 0)
    
    def get_machine_rank_in_type(self, machine_number: int) -> int:
        """指定台番号の機種内順位を取得"""
        return self.machine_rankings.get(machine_number, 0)
    
    def get_daily_machine_summary(self) -> Dict[str, int]:
        """その日の機種別台数サマリーを取得"""
        return self.machine_counts.copy()
    
    def get_machine_name_list(self) -> List[str]:
        """その日の機種名リスト（台数順）を取得"""
        return self.machine_name_list.copy()

class JSONProcessor:
    """JSON ファイル処理クラス"""
    
    def __init__(self, hall_name: str, project_root: str = None):
        """
        Args:
            hall_name: ホール名
            project_root: プロジェクトルート（省略時は自動検出）
        """
        self.hall_name = hall_name
        self.normalizer = DataNormalizer()
        self.count_calculator = MachineCountCalculator()
        # データディレクトリをホール名から構築
        self.project_root = project_root
        self.data_dir = self._build_data_dir()
    
    def _build_data_dir(self) -> str:
        """ホール名からデータディレクトリパスを構築"""
        # プロジェクトルートが指定されていない場合は自動検出
        if self.project_root is None:
            # このファイルの親フォルダから 2 階層遡る（database/ → プロジェクトルート）
            self.project_root = str(Path(__file__).parent.parent)
        
        # data/{hall_name}/ を構築
        data_dir = os.path.join(self.project_root, "data", self.hall_name)
        return data_dir
    
    def get_json_files(self) -> List[str]:
        """
        指定ディレクトリから全JSONファイルを取得
        フォルダが見つからない場合、JSON から正しいホール名を抽出して再試行
        """
        print(f"\n【デバッグ情報】")
        print(f"  project_root: {self.project_root}")
        print(f"  hall_name: {self.hall_name}")
        print(f"  data_dir: {self.data_dir}")
        print(f"  data_dir 存在: {os.path.exists(self.data_dir)}")
        
        json_pattern = os.path.join(self.data_dir, "*.json")
        json_files = glob.glob(json_pattern)
        
        print(f"  glob パターン: {json_pattern}")
        print(f"  検出ファイル数: {len(json_files)}")
        
        if not json_files:
            print(f"\n⚠️  JSON ファイルが見つかりません")
            print(f"  再試行: JSON から正しいホール名を検出...")
            
            # フォルダが存在しない場合、別のホール名で再試行
            actual_hall_name = self._find_correct_hall_folder()
            
            if actual_hall_name and actual_hall_name != self.hall_name:
                print(f"✅ ホール名を修正: '{self.hall_name}' → '{actual_hall_name}'")
                self.hall_name = actual_hall_name
                self.data_dir = self._build_data_dir()
                json_pattern = os.path.join(self.data_dir, "*.json")
                json_files = glob.glob(json_pattern)
                print(f"  再検索後: {len(json_files)}個のファイル検出")
            
            if not json_files:
                raise FileNotFoundError(
                    f"JSONファイルが見つかりません: {json_pattern}\n"
                    f"期待場所: {self.data_dir}"
                )
        
        # ファイル名でソート
        json_files.sort()
        print(f"✅ JSONファイル検出: {len(json_files)}個 (ホール: {self.hall_name})")
        
        return json_files
    
    def _find_correct_hall_folder(self) -> Optional[str]:
        """
        data/ ディレクトリ内のフォルダを検索して、
        JSON ファイル内の hall_name と一致するフォルダを見つける
        """
        try:
            data_root = os.path.join(self.project_root, "data")
            
            print(f"\n  検索開始: {data_root}")
            print(f"  data_root 存在: {os.path.exists(data_root)}")
            
            if not os.path.exists(data_root):
                print(f"  ❌ data フォルダが存在しません")
                return None
            
            # data/ 直下のフォルダをすべて列挙
            all_items = os.listdir(data_root)
            all_subdirs = [d for d in all_items 
                          if os.path.isdir(os.path.join(data_root, d))]
            
            print(f"  見つかったフォルダ: {len(all_subdirs)}個")
            if all_subdirs:
                print(f"    {all_subdirs[:5]}{'...' if len(all_subdirs) > 5 else ''}")
            
            # 各サブディレクトリで JSON ファイルを探す
            for subdir in sorted(all_subdirs):
                subdir_path = os.path.join(data_root, subdir)
                json_files = glob.glob(os.path.join(subdir_path, "*.json"))
                
                if json_files:
                    print(f"\n  フォルダ: {subdir}")
                    print(f"    JSON ファイル: {len(json_files)}個")
                    
                    try:
                        # 最初の JSON ファイルから hall_name を抽出
                        with open(json_files[0], 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            json_hall_name = data.get("hall_name", "")
                            
                            print(f"    JSON の hall_name: '{json_hall_name}'")
                            print(f"    検索対象: '{self.hall_name}'")
                            print(f"    一致: {json_hall_name == self.hall_name}")
                            
                            # JSON 内の hall_name と検索対象が一致したか確認
                            if json_hall_name == self.hall_name:
                                print(f"    ✅ マッチ!")
                                return subdir
                    except Exception as e:
                        print(f"    ⚠️  JSON 読み込みエラー: {str(e)}")
                        continue
            
            print(f"\n  ❌ 一致するホール名が見つかりません")
            return None
        except Exception as e:
            print(f"⚠️  ホール名検索エラー: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    def load_json_file(self, filepath: str) -> Dict[str, Any]:
        """単一JSONファイルを読み込み"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data
        except (json.JSONDecodeError, FileNotFoundError, UnicodeDecodeError) as e:
            raise RuntimeError(f"JSONファイル読み込みエラー: {filepath} - {str(e)}")
    
    def process_machine_data(self, date: str, machine_record: Dict[str, Any], avg_games_per_machine: int = None) -> Dict[str, Any]:
        """個別台データの正規化処理（超簡素版：機種フラグ・同機種台数削除）"""
        try:
            # 必須フィールドの確認と正規化
            machine_name = machine_record.get("機種名", "").strip()
            if not machine_name:
                raise ValueError("機種名が空です")
            
            machine_number = self.normalizer.normalize_machine_number(
                machine_record.get("台番号", "")
            )
            
            # 末尾1桁とゾロ目フラグを計算
            last_digit, is_zorome = self.normalizer.calculate_last_digit_and_zorome(machine_number)
            
            # 機種内順位を取得（同機種台数は削除）
            machine_rank_in_type = self.count_calculator.get_machine_rank_in_type(machine_number)
            
            games = self.normalizer.normalize_games(
                machine_record.get("G数", "")
            )
            
            # 回転数偏差を計算（整数同士の演算）
            games_deviation = self.normalizer.calculate_games_deviation(
                games, avg_games_per_machine
            ) if avg_games_per_machine is not None else 0
            
            diff_coins = self.normalizer.normalize_diff_coins(
                machine_record.get("差枚", "")
            )
            
            bb_count = self.normalizer.normalize_count(
                machine_record.get("BB", "")
            )
            
            rb_count = self.normalizer.normalize_count(
                machine_record.get("RB", "")
            )
            
            # 確率データの処理
            total_prob_frac, total_prob_dec = self.normalizer.normalize_probability(
                machine_record.get("合成確率", "")
            )
            
            bb_prob_frac, bb_prob_dec = self.normalizer.normalize_probability(
                machine_record.get("BB確率", "")
            )
            
            rb_prob_frac, rb_prob_dec = self.normalizer.normalize_probability(
                machine_record.get("RB確率", "")
            )
            
            # 超簡素化された辞書を返す（16要素：機種フラグ・同機種台数削除）
            return {
                "date": date,
                "machine_name": machine_name,
                "machine_number": machine_number,
                "last_digit": last_digit,
                "is_zorome": is_zorome,
                "machine_rank_in_type": machine_rank_in_type,
                "games_normalized": games,
                "games_deviation": games_deviation,
                "diff_coins_normalized": diff_coins,
                "bb_count": bb_count,
                "rb_count": rb_count,
                "total_probability_fraction": total_prob_frac,
                "total_probability_decimal": total_prob_dec,
                "bb_probability_fraction": bb_prob_frac,
                "bb_probability_decimal": bb_prob_dec,
                "rb_probability_fraction": rb_prob_frac,
                "rb_probability_decimal": rb_prob_dec
            }
        
        except Exception as e:
            raise RuntimeError(f"台データ処理エラー (日付: {date}, 台番号: {machine_record.get('台番号', 'N/A')}): {str(e)}")
    
    def process_all_machine_data_for_day(self, date: str, machine_records: List[Dict[str, Any]], avg_games_per_machine: int = None) -> List[Dict[str, Any]]:
        """1日分の全台データを処理（機種内順位計算のみ）"""
        # 1. 仮処理で機種名と台番号を取得
        temp_data_list = []
        for machine_record in machine_records:
            try:
                machine_name = machine_record.get("機種名", "").strip()
                machine_number = self.normalizer.normalize_machine_number(
                    machine_record.get("台番号", "")
                )
                temp_data_list.append({
                    "machine_name": machine_name,
                    "machine_number": machine_number
                })
            except Exception:
                continue  # エラーデータはスキップ
        
        # 2. 機種内順位のみ計算（同機種台数情報は削除）
        self.count_calculator.calculate_same_machine_counts(temp_data_list)
        
        # 3. 正式なデータ処理
        processed_data_list = []
        for machine_record in machine_records:
            try:
                normalized_data = self.process_machine_data(date, machine_record, avg_games_per_machine)
                processed_data_list.append(normalized_data)
            except Exception as e:
                print(f"⚠️ 台データスキップ: {str(e)}")
                continue
        
        return processed_data_list
    
    def get_daily_machine_summary(self) -> Dict[str, int]:
        """その日の機種別台数サマリーを取得"""
        return self.count_calculator.get_daily_machine_summary()
    
    def get_machine_name_list(self) -> List[str]:
        """その日の機種名リスト（台数順）を取得"""
        return self.count_calculator.get_machine_name_list()

# テスト実行時のみの処理
if __name__ == "__main__":
    print("JSONProcessor単体テストは実行できません。")
    print("main.pyから実行してください。")