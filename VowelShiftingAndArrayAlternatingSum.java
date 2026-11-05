import java.util.Scanner;

public class VowelShiftingAndArrayAlternatingSum {

    public static void main(String[] args) {

        Scanner sc = new Scanner(System.in);
        String inputStr = "";

        while (true) {

            System.out.println("Choose an option:");
            System.out.println("1. Shift vowels in the string");
            System.out.println("2. Calculate total sum of alternating sums of arrays");
            System.out.println("3. Replace consonants with 'z'");
            System.out.println("4. Count the number of vowels in a string");
            System.out.println("5. Exit");

            int choice = sc.nextInt();
            sc.nextLine(); // Clear buffer

            switch (choice) {

                case 1:

                    System.out.println("Enter the string:");
                    inputStr = sc.nextLine();

                    String shiftedVowelStr = shiftVowels(inputStr);

                    System.out.println("Vowel-shifted string: " + shiftedVowelStr);
                    break;

                case 2:

                    System.out.println("Enter the size of the arrays:");
                    int size = sc.nextInt();

                    int[] arr1 = new int[size];
                    int[] arr2 = new int[size];

                    System.out.println("Enter elements for the first array:");
                    for (int i = 0; i < size; i++) {
                        arr1[i] = sc.nextInt();
                    }

                    System.out.println("Enter elements for the second array:");
                    for (int i = 0; i < size; i++) {
                        arr2[i] = sc.nextInt();
                    }

                    int totalSum = calculateTotalAlternatingSum(arr1, arr2);

                    System.out.println("Total sum of alternating sums: " + totalSum);
                    break;

                case 3:

                    System.out.println("Enter the string to replace consonants:");
                    inputStr = sc.nextLine();

                    String consonantReplacedStr = replaceConsonants(inputStr);

                    System.out.println("String with consonants replaced: " + consonantReplacedStr);
                    break;

                case 4:

                    System.out.println("Enter the string to count vowels:");
                    inputStr = sc.nextLine();

                    int vowelCount = countVowels(inputStr);

                    System.out.println("Number of vowels in the string: " + vowelCount);
                    break;

                case 5:

                    System.out.println("Exiting...");
                    sc.close();
                    return;

                default:

                    System.out.println("Invalid option.");
            }
        }
    }

    // Function to shift vowels in a string
    public static String shiftVowels(String str) {

        String vowels = "aeiouAEIOU";
        String shiftedVowels = "eiouaEIOUA";

        StringBuilder result = new StringBuilder();

        for (int i = 0; i < str.length(); i++) {
            char ch = str.charAt(i);
            int index = vowels.indexOf(ch);
            if (index != -1) {
                result.append(shiftedVowels.charAt(index));
            } else {
                result.append(ch);
            }
        }

        return result.toString();
    }

    // Function to calculate total alternating sum of two arrays
    public static int calculateTotalAlternatingSum(int[] arr1, int[] arr2) {

        int totalSum = 0;

        for (int i = 0; i < arr1.length; i++) {
            if (i % 2 == 0) {
                totalSum += arr1[i] + arr2[i];
            } else {
                totalSum += arr1[i] - arr2[i];
            }
        }

        return totalSum;
    }

    // Function to replace consonants with 'z'
    public static String replaceConsonants(String str) {

        String vowels = "aeiouAEIOU";
        StringBuilder result = new StringBuilder();

        for (int i = 0; i < str.length(); i++) {
            char ch = str.charAt(i);
            if (vowels.indexOf(ch) != -1) {
                result.append(ch);
            } else {
                result.append('z');
            }
        }

        return result.toString();
    }

    // Function to count the number of vowels in a string
    public static int countVowels(String str) {

        int count = 0;
        String vowels = "aeiouAEIOU";

        for (int i = 0; i < str.length(); i++) {
            if (vowels.indexOf(str.charAt(i)) != -1) {
                count++;
            }
        }

        return count;
    }
}
